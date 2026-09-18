struct BrushUniforms {
  strength : f32,
  radius : f32,
  spacing : f32,
  invert : u32,
  falloff_kind : u32,
  falloff_shape : u32,
  nonaccum : u32,
  grab_dab_gen : u32,
  falloff_dir : vec3<f32>,
  unbounded_extent : f32,
  falloff_extent : vec3<f32>,
  coord_space : u32,
  tex_repeat : f32,
  stroke_path_count : u32,
  typed_gain : f32,
  typed_count : i32,
  typed_enabled : u32,
  typed_low : i32,
  typed_high : i32,
  typed_static : u32,
  typed_limited : i32,
}

struct CtxUniforms {
  surfacePos : vec3<f32>,
  surfaceNo : vec3<f32>,
  render_matrix : mat4x4<f32>,
  view_dir : vec3<f32>,
  vn_enabled : u32,
  vn_limit : f32,
  vn_falloff : f32,
  vn_cull : u32,
  _vn_pad : u32,
  typed_work : i32,
  typed_gate : u32,
}

struct NodeMeta {
  vert_offset : u32,
  vert_count : u32,
}

struct StrokeSample {
  pos : vec3<f32>,
  normal : vec3<f32>,
  arclen : f32,
}

@group(0) @binding(0) var<storage, read_write> co_buf : array<vec3<f32>>;

@group(0) @binding(1) var<storage, read_write> no_buf : array<vec3<f32>>;

@group(0) @binding(2) var<storage, read_write> mask_buf : array<f32>;

@group(0) @binding(3) var<storage, read> unique_verts : array<u32>;

@group(0) @binding(4) var<storage, read> nodes : array<NodeMeta>;

@group(0) @binding(5) var<uniform> brush_u : BrushUniforms;

@group(0) @binding(6) var<uniform> ctx_u : CtxUniforms;

@group(0) @binding(7) var<uniform> falloff_lut : array<vec4<f32>, 64>;

@group(0) @binding(8) var brush_tex : texture_2d<f32>;

@group(0) @binding(9) var brush_samp : sampler;

@group(0) @binding(10) var<storage, read> stroke_path : array<StrokeSample>;

@group(0) @binding(25) var<storage, read_write> sb_disp : array<vec3<f32>>;

@group(0) @binding(24) var<storage, read> automask : array<f32>;

fn sb_lut(i : i32) -> f32 {
  return falloff_lut[(i >> 2)][(i & 3)];
}

fn brush_falloff(t : f32) -> f32 {
  if ((brush_u.falloff_kind == 1u)) {
    return t;
  } else if ((brush_u.falloff_kind == 2u)) {
    let sb_u = (1.0 - t);
    return exp(((-(9.0) * sb_u) * sb_u));
  } else if ((brush_u.falloff_kind == 3u)) {
    let sb_c = clamp(t, 0.0, 1.0);
    let sb_s = (sb_c * 255.0);
    let sb_i = i32(floor(sb_s));
    if ((sb_i >= 255)) {
      return sb_lut(255);
    }
    let sb_f = (sb_s - f32(sb_i));
    return ((sb_lut(sb_i) * (1.0 - sb_f)) + (sb_lut((sb_i + 1)) * sb_f));
  }
  return ((t * t) * (3.0 - (2.0 * t)));
}

fn brush_falloff_dist(delta : vec3<f32>) -> f32 {
  let sb_inv_r = (1.0 / brush_u.radius);
  if ((brush_u.falloff_shape == 1u)) {
    let sb_a = abs(delta);
    return (max(sb_a.x, max(sb_a.y, sb_a.z)) * sb_inv_r);
  } else if ((brush_u.falloff_shape == 2u)) {
    return (abs(dot(delta, brush_u.falloff_dir)) * sb_inv_r);
  } else if ((brush_u.falloff_shape == 3u)) {
    let sb_n = normalize(ctx_u.surfaceNo);
    var sb_tang = (brush_u.falloff_dir - (sb_n * dot(brush_u.falloff_dir, sb_n)));
    var sb_tl = length(sb_tang);
    if ((sb_tl < 0.000001)) {
      let sb_ref = select(vec3<f32>(1.0, 0.0, 0.0), vec3<f32>(0.0, 0.0, 1.0), (abs(sb_n.z) < 0.99899999999999999911));
      sb_tang = cross(sb_ref, sb_n);
      sb_tl = length(sb_tang);
    }
    sb_tang = (sb_tang / sb_tl);
    let sb_lat = cross(sb_n, sb_tang);
    let sb_dn = (abs(dot(delta, sb_tang)) / brush_u.falloff_extent.x);
    let sb_d1 = (abs(dot(delta, sb_lat)) / brush_u.falloff_extent.y);
    let sb_d2 = (abs(dot(delta, sb_n)) / brush_u.falloff_extent.z);
    return (max(sb_dn, max(sb_d1, sb_d2)) * sb_inv_r);
  }
  return (length(delta) * sb_inv_r);
}

fn brush_view_normal(vid : u32) -> f32 {
  if ((ctx_u.vn_enabled == 0u)) {
    return 1.0;
  }
  let sb_no = no_buf[vid];
  let sb_nl = length(sb_no);
  let sb_vl = length(ctx_u.view_dir);
  if (((sb_nl <= 0.000000001) || (sb_vl <= 0.000000001))) {
    return 1.0;
  }
  var sb_d = (-(dot(sb_no, ctx_u.view_dir)) / (sb_nl * sb_vl));
  if ((ctx_u.vn_cull == 0u)) {
    sb_d = abs(sb_d);
  }
  sb_d = clamp(sb_d, -(1.0), 1.0);
  let sb_ang = acos(sb_d);
  if ((sb_ang >= ctx_u.vn_limit)) {
    return 0.0;
  }
  if ((ctx_u.vn_falloff <= 0.000001)) {
    return 1.0;
  }
  let sb_ramp = (ctx_u.vn_limit - ctx_u.vn_falloff);
  if ((sb_ang <= sb_ramp)) {
    return 1.0;
  }
  return ((ctx_u.vn_limit - sb_ang) / ctx_u.vn_falloff);
}

fn brush_automasks(vid : u32) -> f32 {
  return (automask[vid] * brush_view_normal(vid));
}

fn brush_masks(vid : u32, m : f32) -> f32 {
  return (brush_automasks(vid) * (1.0 - m));
}

fn brush_unbounded_window(p : vec3<f32>) -> f32 {
  let sb_R = (brush_u.radius * brush_u.unbounded_extent);
  if (!((sb_R > 0.0))) {
    return 1.0;
  }
  let sb_d = length((p - ctx_u.surfacePos));
  let sb_t = clamp(((sb_R - sb_d) / (0.2000000000000000111 * sb_R)), 0.0, 1.0);
  return ((sb_t * sb_t) * (3.0 - (2.0 * sb_t)));
}

fn brush_stroke_uv(co : vec3<f32>) -> vec2<f32> {
  if ((brush_u.stroke_path_count == 0u)) {
    return vec2<f32>(0.0, 0.0);
  }
  if ((brush_u.stroke_path_count == 1u)) {
    return vec2<f32>(stroke_path[0].arclen, length((co - stroke_path[0].pos)));
  }
  var sb_best_dist = 340282299999999994960115009090224128000.0;
  var sb_best_arc = 0.0;
  var sb_best_lat = 0.0;
  for(var i = 0u; ((i + 1u) < brush_u.stroke_path_count); i = (i + 1u)) {
    let sb_a = stroke_path[i].pos;
    let sb_ab = (stroke_path[(i + 1u)].pos - sb_a);
    let sb_len2 = dot(sb_ab, sb_ab);
    var sb_t = 0.0;
    if ((sb_len2 > 0.0)) {
      sb_t = (dot((co - sb_a), sb_ab) / sb_len2);
    }
    sb_t = clamp(sb_t, 0.0, 1.0);
    let sb_d = length((co - (sb_a + (sb_ab * sb_t))));
    if ((sb_d < sb_best_dist)) {
      sb_best_dist = sb_d;
      sb_best_arc = (stroke_path[i].arclen + ((stroke_path[(i + 1u)].arclen - stroke_path[i].arclen) * sb_t));
      sb_best_lat = sb_d;
    }
  }
  return vec2<f32>(sb_best_arc, sb_best_lat);
}

fn brush_view_uv(co : vec3<f32>) -> vec2<f32> {
  let sb_p = (ctx_u.render_matrix * vec4<f32>(co, 1.0));
  var sb_w = sb_p.w;
  if ((abs(sb_w) <= 0.000001)) {
    sb_w = 1.0;
  }
  return (((sb_p.xy / sb_w) * 0.5) + vec2<f32>(0.5, 0.5));
}

fn brush_view_aspect() -> f32 {
  let sb_m = ctx_u.render_matrix;
  let sb_r0 = length(vec3<f32>(sb_m[0][0], sb_m[1][0], sb_m[2][0]));
  let sb_r1 = length(vec3<f32>(sb_m[0][1], sb_m[1][1], sb_m[2][1]));
  if (((sb_r0 > 0.000000000001) && (sb_r1 > 0.000000000001))) {
    return (sb_r1 / sb_r0);
  }
  return 1.0;
}

fn brush_sample_tex(co : vec3<f32>, no : vec3<f32>) -> f32 {
  _ = no;
  var sb_uv : vec2<f32>;
  if ((brush_u.coord_space == 1u)) {
    sb_uv = brush_view_uv(co);
  } else if ((brush_u.coord_space == 2u)) {
    var sb_ruv = brush_view_uv(co);
    sb_ruv.x = (sb_ruv.x * brush_view_aspect());
    sb_uv = fract((sb_ruv * brush_u.tex_repeat));
  } else if ((brush_u.coord_space == 3u)) {
    sb_uv = brush_stroke_uv(co);
  } else if ((brush_u.coord_space == 4u)) {
    let sb_n = normalize(ctx_u.surfaceNo);
    var sb_ref = vec3<f32>(0.0, 0.0, 1.0);
    if ((abs(sb_n.z) >= 0.99899999999999999911)) {
      sb_ref = vec3<f32>(1.0, 0.0, 0.0);
    }
    let sb_t1 = normalize(cross(sb_ref, sb_n));
    let sb_t2 = cross(sb_n, sb_t1);
    let sb_rel = (co - ctx_u.surfacePos);
    var sb_inv_d = 1.0;
    if ((brush_u.radius > 0.000001)) {
      sb_inv_d = (1.0 / (2.0 * brush_u.radius));
    }
    sb_uv = ((vec2<f32>(dot(sb_rel, sb_t1), dot(sb_rel, sb_t2)) * sb_inv_d) + vec2<f32>(0.5, 0.5));
  } else {
    sb_uv = fract(((co.xy * 0.5) + vec2<f32>(0.5, 0.5)));
  }
  let sb_dim = vec2<f32>(textureDimensions(brush_tex));
  let sb_fx = ((sb_uv.x * sb_dim.x) - 0.5);
  let sb_fy = ((sb_uv.y * sb_dim.y) - 0.5);
  let sb_x0 = floor(sb_fx);
  let sb_y0 = floor(sb_fy);
  let sb_tx = (sb_fx - sb_x0);
  let sb_ty = (sb_fy - sb_y0);
  let sb_w = i32(sb_dim.x);
  let sb_h = i32(sb_dim.y);
  let sb_x0c = clamp(i32(sb_x0), 0, (sb_w - 1));
  let sb_y0c = clamp(i32(sb_y0), 0, (sb_h - 1));
  let sb_x1c = clamp((i32(sb_x0) + 1), 0, (sb_w - 1));
  let sb_y1c = clamp((i32(sb_y0) + 1), 0, (sb_h - 1));
  let sb_p00 = textureLoad(brush_tex, vec2<i32>(sb_x0c, sb_y0c), 0).r;
  let sb_p10 = textureLoad(brush_tex, vec2<i32>(sb_x1c, sb_y0c), 0).r;
  let sb_p01 = textureLoad(brush_tex, vec2<i32>(sb_x0c, sb_y1c), 0).r;
  let sb_p11 = textureLoad(brush_tex, vec2<i32>(sb_x1c, sb_y1c), 0).r;
  let sb_a = ((sb_p00 * (1.0 - sb_tx)) + (sb_p10 * sb_tx));
  let sb_b = ((sb_p01 * (1.0 - sb_tx)) + (sb_p11 * sb_tx));
  return ((sb_a * (1.0 - sb_ty)) + (sb_b * sb_ty));
}

fn brush_strength(p : vec3<f32>) -> f32 {
  let sb_t = (1.0 - min(brush_falloff_dist((p - ctx_u.surfacePos)), 1.0));
  let sb_s = ((brush_u.strength * brush_falloff(sb_t)) * brush_sample_tex(p, ctx_u.surfaceNo));
  return select(sb_s, -(sb_s), (brush_u.invert != 0u));
}

@compute @workgroup_size(64)
fn main(@builtin(local_invocation_index) lid : u32, @builtin(workgroup_id) gid : vec3<u32>) {
  let sb_node = nodes[gid.x];
  if ((lid >= sb_node.vert_count)) {
    return;
  }
  let sb_vidx = unique_verts[(sb_node.vert_offset + lid)];
  let sb_base : vec3<f32> = (co_buf[sb_vidx] - select(vec3<f32>(0.0), sb_disp[sb_vidx], (brush_u.nonaccum != 0u)));
  var v_co : vec3<f32> = sb_base;
  var v_no : vec3<f32> = no_buf[sb_vidx];
  var v_mask : f32 = mask_buf[sb_vidx];
  var do_apply : bool = ((((brush_u.typed_enabled != 0u) && (brush_u.typed_static != 0u)) && (ctx_u.typed_gate != 0u)) && !((brush_u.invert != 0u)));
  if (((do_apply && (brush_u.typed_count == 16777217)) && (ctx_u.typed_work == 16777218))) {
    v_co += vec3<f32>(brush_u.typed_gain, 0.0, 0.0);
  }
  let sb_delta = (v_co - sb_base);
  if ((brush_u.nonaccum != 0u)) {
    co_buf[sb_vidx] = (co_buf[sb_vidx] + sb_delta);
    sb_disp[sb_vidx] = (sb_disp[sb_vidx] + sb_delta);
  } else {
    co_buf[sb_vidx] = v_co;
  }
  no_buf[sb_vidx] = v_no;
  mask_buf[sb_vidx] = v_mask;
}
