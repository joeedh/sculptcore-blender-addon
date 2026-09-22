# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The interactive stroke modal operator: ``SCULPTCORE_OT_brush_stroke``.

Wires the per-stroke setup (``invoke``), the pointer-event loop (``modal``),
and stroke teardown (``_finish``/``cancel``) onto the dab-application mixins
in ``operator_apply``/``operator_preview``."""

import bpy

from .. import convert, cursor, engine, mapping, stroke_input, symmetry, texture, undo
from ..brush_properties import shift_smooth
from . import _draw
from .dab import build_program
from .dyntopo import DYNTOPO_EDGE_MIN_FACTOR, build_dyntopo_params, configure_dyntopo_params, dyntopo_max_edge
from .operator_apply import _GenericApplyMixin
from .operator_preview import _PreviewMixin
from .raycast import _cursor_on_anchor_plane, _ray_origin_dir, raycast
from .session import (_ensure_brush, _ensure_executor, program_grids_capable, stroke_begin, stroke_end,
                      toggle_kernel_name)
from .spacer import StrokeSpacer


class SCULPTCORE_OT_brush_stroke(_GenericApplyMixin, _PreviewMixin, bpy.types.Operator):
    bl_idname = "sculptcore.brush_stroke"
    bl_label = "SculptCore Stroke"
    # No 'UNDO': the stroke pushes its own CUSTOM_MODE step (delta undo) at end
    # via undo.push, instead of a full memfile snapshot. The Mesh ID stays
    # authoritative through the mode's flush for save/render.
    bl_options = set()

    # SKIP_SAVE (like vanilla paint_stroke_operator_properties): without it a
    # plain-LMB stroke reuses the last-used value, so one Ctrl/Shift stroke
    # would latch INVERT/SMOOTH permanently.
    mode: bpy.props.EnumProperty(
        name="Stroke Mode",
        items=(
            ('NORMAL', "Regular", "Apply brush normally"),
            ('INVERT', "Invert", "Invert action of brush for duration of stroke"),
            ('SMOOTH', "Smooth", "Switch brush to smooth mode for duration of stroke"),
            ('MASK', "Mask", "Switch brush to the mask brush for duration of stroke"),
        ),
        default='NORMAL',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (
            ob is not None
            and ob.mode == 'CUSTOM'
            and ob.custom_mode == "sculptcore.sculpt"
            and ob.name in engine.sessions
        )

    def invoke(self, context, event):
        ob = context.active_object
        # A foreign memfile undo may have changed the mesh under us (custom-undo
        # modes skip the generic refresh); rebuild the session before sculpting
        # if the engine no longer matches the Mesh.
        convert.resync_if_diverged(ob)
        self.session = engine.sessions[ob.name]
        self.brush = context.tool_settings.sculpt.brush
        self._generic = None
        self._generic_smooth_command = None
        self._family_scale = 1.0
        if self.session.generic_runtime is not None:
            self.session.generic_runtime.close()
            self.session.generic_runtime = None
        mgr = engine.manager()
        if self.mode in {'SMOOTH', 'MASK'}:
            # Shift-stroke smooths (colour blur over a paint brush), Alt-stroke
            # masks — both with the active brush's radius (vanilla brush_toggle
            # semantics); a generic Shift-smooth takes its strength, kernel and
            # scalars from the Shift-smooth settings instead of the brush. The
            # pick lives in toggle_kernel_name.
            kernel_name = toggle_kernel_name(self.mode, self.brush, self.session, context.scene)
            self.kernel = (int(mgr.get("sculptcore::brush::SculptBrushes").items[kernel_name])
                           if self.brush else None)
        else:
            self.kernel = mapping.kernel_enum(mgr, self.brush) if self.brush else None
        if self.kernel is None:
            self.report({'WARNING'}, "SculptCore: brush type has no kernel")
            return {'CANCELLED'}

        settings = None
        if context.scene.sculptcore_generic_properties:
            from ..brush_properties.stroke_settings import capture_stroke
            from ..brush_properties.registry import PropertyError
            kernel_name = next(name for name, value in mgr.get("sculptcore::brush::SculptBrushes").items.items()
                               if int(value) == self.kernel)
            try:
                settings = capture_stroke(self.brush, context.scene, kernel_name=kernel_name)
            except PropertyError as error:
                self.report({'ERROR'}, "SculptCore: " + str(error))
                return {'CANCELLED'}

        self._last_flush = 0.0
        # Gate closed at stroke start: the first refresh waits for the frame
        # the invoke's own tag_redraw requests (≤ one frame period), keeping
        # the invariant one refresh per presented frame from dab one.
        self._flush_frame = _draw._frames_presented
        _draw._draw_counter_push()
        self._dab_count = 0
        # Object-space running sum of this stroke's dab centers; written to
        # Paint.stroke_pivot (world space) at stroke end so the viewport orbits
        # around the last stroke, as vanilla sculpt does. Symmetry mirrors are
        # excluded — vanilla accumulates only the primary center too.
        self._pivot_sum = [0.0, 0.0, 0.0]
        self._pivot_n = 0
        # A kernel toggle (smooth/mask) replaces the brush's own kernel, so
        # brush-type-derived behavior (grab anchoring, face-set group
        # assignment, autosmooth chaining) is bypassed for the stroke.
        kernel_toggle = self.mode in {'SMOOTH', 'MASK'}
        # Layer brush: make sure the layerdraw kernel has a write target
        # before any capability query -- on multires the grids roster itself
        # flips on the live edit target (LD3).
        if not kernel_toggle and self.brush.sculpt_brush_type == 'LAYER':
            from .. import layers
            layers.ensure_stroke_target(context, ob, self.session)
        self._grab_class = not kernel_toggle and mapping.is_grab_class(self.brush)
        # Twist: the grab path, but the kernel takes the pointer's dial angle
        # about the stroke start (mapping.DIAL_ANGLE); the dial is created
        # with the anchor, on the first surface hit.
        self._dial = None
        self._dial_angle = (not kernel_toggle and self._grab_class
                            and self.brush.sculpt_brush_type in mapping.DIAL_ANGLE)
        # Snake hook's kernel reads the grab ctx vectors (see
        # mapping.is_snake_hook) and its influence region walks out with the
        # extruded tip rather than tracking the surface under the cursor — see
        # _snake_hook_advance for the state these four fields carry.
        self._snake_hook = not kernel_toggle and mapping.is_snake_hook(self.brush)
        self._sh_origin = None
        self._sh_normal = None
        self._sh_center = None
        self._sh_plane = None
        self._sh_delta = (0.0, 0.0, 0.0)
        self._preview_origin = None
        # Smoothing strokes (Shift-toggle or a relaxation brush — Smooth, the
        # feature-align Slide Relax) iterate per dab by strength, vanilla-style
        # (see smooth_iteration_strengths).
        self._smooth_stroke = (
            self.mode == 'SMOOTH'
            or (not kernel_toggle and mapping.is_relaxation(self.brush)))
        # A generic Shift-smooth over a sculpt brush: strength, passes ceiling
        # and kernel scalars come from the Shift-smooth settings
        # (brush_properties.shift_smooth), not the active brush.
        self._shift_smooth = (kernel_toggle and self.mode == 'SMOOTH' and settings is not None)
        self._smooth_strength_max = 1.0
        self._toggle_extras = None
        if self._shift_smooth:
            self._smooth_strength_max = shift_smooth.STRENGTH_MAX
            projection = settings.value(shift_smooth.PROJECTION)
            if kernel_name == 'FEATURE_ALIGN':
                self._toggle_extras = (('rake', settings.value(shift_smooth.RAKE_SHIFT)),
                                       ('projection', projection))
            elif kernel_name == 'BSMOOTH':
                self._toggle_extras = (('projection', projection),)
            else:
                self._toggle_extras = ()
        # Anchored / Drag-Dot stroke methods drive the engine preview-dab API
        # (one live, non-compounding dab per input) instead of the spacer. DOTS/
        # SPACE (and, for now, AIRBRUSH/LINE/CURVE) use the spacer path; grab
        # anchors via its own kernel, so it keeps the grab path.
        self._stroke_method = self.brush.stroke_method
        self._preview_method = (not self._grab_class
                                and self._stroke_method in {'ANCHORED', 'DRAG_DOT'})
        # Generic strokes install only resolved settings. Legacy strokes retain
        # their pressure LUTs and native stacks, including smooth decomposition.
        sc_brush = _ensure_brush(self.session)
        self._pressure_strength_lut = None
        self._pressure_size_lut = None
        if settings is not None:
            from ..brush_properties.stroke_runtime import StrokeRuntime
            try:
                self._generic = StrokeRuntime(settings, self.session, self.kernel)
            except (PropertyError, ValueError, RuntimeError) as error:
                _draw._draw_counter_pop()
                self.report({'ERROR'}, "SculptCore: " + str(error))
                return {'CANCELLED'}
            self.session.generic_runtime = self._generic
            # Color is a native vector outside the generic scalar catalogue.
            if self.brush.sculpt_brush_type == 'PAINT':
                color = sc_brush.brushColor.vec
                color[0], color[1], color[2], color[3] = *self.brush.color, 1.0
        else:
            strength_prop, size_prop = mapping.pressure_prop_names(self.brush)
            use_strength = not self._grab_class and getattr(self.brush, strength_prop)
            use_size = not self._grab_class and getattr(self.brush, size_prop)
            self._pressure_strength_lut = (
                mapping.sample_pressure_curve(self.brush, 'curve_strength') if use_strength else None)
            self._pressure_size_lut = (
                mapping.sample_pressure_curve(self.brush, 'curve_size') if use_size else None)
            curve_cache = self.session.curve_cache
            paint = context.tool_settings.sculpt
            mapping.apply_brush_settings(
                self.brush, paint.unified_paint_settings, sc_brush, paint=paint, cache=curve_cache)
            from .. import engine_props
            engine_props.sync_authored(self.session, _ensure_executor(self.session), self.kernel)
            mapping.apply_pressure_dynamics(
                self.brush, sc_brush, cache=curve_cache,
                use_strength=use_strength and not self._smooth_stroke,
                use_size=use_size and not self._smooth_stroke)
        # Tiled texture scale uses the same captured size owner as the stroke.
        texture.apply_texture(self.brush, sc_brush, context, session=self.session)
        if texture.needs_render_matrix(self.brush):
            texture.apply_render_matrix(context, _ensure_executor(self.session))
        # UV slide-reprojection (scene toggle): the executor re-anchors moved
        # verts' UVs for the smooth-family kernels. Any stroke that may run
        # one (smooth brush, Shift-smooth, autosmooth chain) diverges the
        # engine UVs from the Mesh, so the flush must write them back.
        sc_brush.reproject_uvs = context.scene.sculptcore_reproject_uvs
        if sc_brush.reproject_uvs:
            self.session.uv_dirty = True
        # "Adjust Strength for Spacing": constant for the stroke, folded into
        # every dab's strength write — together with any per-type strength
        # compensation (kernel-scale parity, see mapping.STRENGTH_SCALE).
        self._family_scale = (mapping.STRENGTH_SCALE.get(self.brush.sculpt_brush_type, 1.0)
                              if not kernel_toggle else 1.0)
        self._overlap = (self._generic.settings.overlap() if self._generic else
                         mapping.overlap_attenuation(self.brush)) * self._family_scale
        self._anchor = None
        self._anchor_normal = None
        self._drag_origin = None
        # Dab spacing along the stroke path (engine StrokeSpacer semantics:
        # interval = world radius x spacing fraction). Grab-class ignores it.
        self._spacer = StrokeSpacer()
        self._input_sampler = stroke_input.InputSampler(context.scene.sculptcore_speed_reference)
        # Trailing-flush state, refreshed on every move (see _dab_at); defaults
        # cover a commit with no intervening move.
        self._last_invert = False
        self._last_pressure = 1.0
        self._last_spacing = 0.0
        # Dyntopo cadence bookkeeping: accumulated stroke arc length and the
        # arc length of the last remesh. -inf so the first dab always remeshes.
        self._stroke_s = 0.0
        self._last_dyntopo_s = float("-inf")
        self._dyntopo_spacing = 0.0
        # Plane-mirror symmetry: one sign vector per reflection (empty = off).
        self._mirror_signs = symmetry.mirror_signs(symmetry.axes_from_mesh(ob.data))
        # Face-set brushes paint a fresh group id per stroke. ensureFaceGroups
        # flood-fills a first-ever group attr with the mesh's default id (so
        # unpainted faces read as Blender's default set, not scattered zeros);
        # newFaceGroupId skips that default, so a painted set is never the
        # invisible one (extending the default set stays an explicit sample of
        # an existing face's id, never an allocation).
        self.session.last_stroke_face_sets = False
        if not kernel_toggle and self.brush.sculpt_brush_type in mapping.FACE_SET_TYPES:
            brush = _ensure_brush(self.session)
            if self.session.multires_ptr:
                # Face sets are a Derived grid attribute, so the engine roster
                # refuses the grids path and the stroke runs mesh-path on the
                # slot's derived `group` column. The slot is lazy: without this
                # the wrapper below binds a null Mesh* and the group calls fault.
                convert.ensure_multires_slot(self.session)
            mesh_obj = self.session.mesh()
            mesh_obj.ensureFaceGroups()
            brush.activeGroup = int(mesh_obj.newFaceGroupId())
            # On multires this paints the SLOT's derived column, which does
            # not persist, so undo.push scatters it home to the cage (§6 of
            # plans/grid-domain-attributes.md).
            self.session.last_stroke_face_sets = True
        # Colour is the other layer with no multires domain to live in: the
        # store channel and the slot column both die with the session, so the
        # cage is where a paint stroke's dabs land (§6.3 of
        # plans/grid-domain-attributes.md). A Shift-smooth over a paint brush
        # edits the same cage column through the engine's cage-dab entry, so
        # it snapshots (and undoes) as a colour stroke too.
        self._cage_smooth = (kernel_toggle and self.mode == 'SMOOTH'
                             and self.session.multires_ptr is not None
                             and self.brush.sculpt_brush_type in mapping.COLOR_TYPES)
        self.session.last_stroke_color = (
            (not kernel_toggle and self.brush.sculpt_brush_type in mapping.COLOR_TYPES)
            or self._cage_smooth)
        # Both flags are known now, and the cage is untouched: this is the only
        # place the pre-stroke columns can still be read, since every dab from
        # here on writes them.
        if self.session.multires_ptr:
            undo.snapshot_cage_columns(self.session)
        # Dyntopo (scene toggle) and autosmooth both run through a program;
        # neither applies to grab-class nor to a Shift-smooth stroke.
        # Autosmooth also skips the smooth brush itself.
        scene = context.scene
        smooth_factor = 0.0
        if (not self._grab_class and not kernel_toggle
                and not mapping.is_relaxation(self.brush)
                and self.brush.auto_smooth_factor > 0.0):
            smooth_factor = self.brush.auto_smooth_factor

        if self._generic and not self._grab_class and not kernel_toggle and not self._smooth_stroke:
            snapshot = self._generic.settings.snapshot('sculptcore.brush.autosmooth')
            smooth_factor = snapshot.value
            if any(layer.enabled for layer in snapshot.stack):
                smooth_factor = max(smooth_factor, 1e-8)
        self._generic_smooth_command = 1 if smooth_factor > 0 else None
        self._dyntopo = None
        self._program = None
        self._detail_factor = None
        # A multires level mesh is derived from the grid store, so remeshing it
        # strands every level's displacement and the grid map; the engine
        # refuses the dab (Mesh::topoLocked) and this keeps the stroke from
        # opening a topology-logging undo step for changes that never come.
        # A Shift-smooth remeshes only when its own Dyntopo setting asks
        # (colour blur never does: it moves no geometry).
        shift_dyntopo = (self._shift_smooth and kernel_name in {'BSMOOTH', 'FEATURE_ALIGN'}
                         and settings.value(shift_smooth.DYNTOPO))
        if (not self._grab_class and (not kernel_toggle or shift_dyntopo)
                and self.session.multires_ptr is None
                and getattr(scene, "sculptcore_dyntopo", False)):
            self._program = build_program(self.session, self.kernel, smooth_factor)
            # Detail size from Blender's dyntopo settings (see
            # dyntopo_max_edge). CONSTANT/MANUAL fix the edge length for the
            # stroke; RELATIVE/BRUSH reduce to `factor * world_radius`,
            # re-applied per remesh dab (the radius is depth-dependent).
            sculpt_settings = context.tool_settings.sculpt
            pixel_radius = self._pixel_radius(context)
            if sculpt_settings.detail_type_method in {'CONSTANT', 'MANUAL'}:
                l_max = dyntopo_max_edge(sculpt_settings, ob, 0.0, pixel_radius,
                                         context.preferences.system.pixel_size)
            else:
                # Factor per unit world radius (formulas are linear in it).
                self._detail_factor = dyntopo_max_edge(
                    sculpt_settings, ob, 1.0, pixel_radius,
                    context.preferences.system.pixel_size)
                l_max = self._detail_factor  # placeholder; set per remesh dab
            self._dyntopo = build_dyntopo_params(
                self.session, l_max, l_max * DYNTOPO_EDGE_MIN_FACTOR)
            configure_dyntopo_params(self._dyntopo, scene,
                                     sculpt_settings.detail_refine_method)
            # Remesh cadence in the same (pixel) units stroke_s accumulates: a
            # fraction of the brush diameter of stroke travel per remesh pass.
            frac = max(getattr(scene, "sculptcore_dyntopo_spacing", 0.5), 0.0)
            self._dyntopo_spacing = frac * 2.0 * pixel_radius
        elif smooth_factor > 0.0:
            self._program = build_program(self.session, self.kernel, smooth_factor)

        # A/B (design/cpp-dab-loop.md, variant B): run the per-dab loop of a
        # plain spaced stroke engine-side, batched per pointer event. Python
        # keeps the spacer walk and ray synthesis; everything the flat batch
        # cannot express — grab anchoring, preview dabs, snake hook's walking
        # tip, multi-pass smooth, dyntopo — stays on the per-dab path above.
        # Programs (autosmooth) batch on both domains via the *_dabBatchProgram
        # variants (S4 grids, S5 mesh).
        # A legacy PLANE stroke in Swap mode trades its reaches per dab, which
        # a batch's shared uniforms cannot express (the generic runtime folds
        # the swap into each row's payload instead).
        self._batch = (not self._grab_class and not self._preview_method
                       and not self._snake_hook and not self._smooth_stroke
                       and self._dyntopo is None
                       and not (self._generic is None and not kernel_toggle
                                and mapping.plane_swap_on_invert(self.brush))
                       and getattr(scene, "sculptcore_cpp_dab_loop", False))
        # Set when a batch call returns the engine's stroke-dead sentinel
        # (stale grids domain); invoke/modal tear the stroke down through
        # _finish rather than falling back mid-stroke.
        self._engine_dead = False
        if self._batch:
            import numpy as np
            self._mirror_flat = np.ascontiguousarray(
                np.array(self._mirror_signs, dtype=np.float32).reshape(-1))
            # The engine-side node filter widens to the kernel's field radius,
            # same as brush_policy.filter_radius with no drag; latching never
            # applies here (grab-class is excluded from the batch path). For a
            # program this is the main kernel's multiplier — the chained
            # BSMOOTH is never unbounded.
            from .. import brush_policy
            self._filter_mul = (
                float(_ensure_brush(self.session).unboundedExtent)
                if brush_policy.for_kernel(self.kernel).unbounded else 1.0)

        # Anchored refuses a stroke that starts off the surface — checked before
        # opening the undo step, so a refusal leaves no empty step behind.
        if self._preview_method and self._stroke_method == 'ANCHORED':
            a_origin, a_dir = _ray_origin_dir(
                context, (event.mouse_region_x, event.mouse_region_y))
            a_hit = raycast(self.session, a_origin, a_dir)
            if a_hit is None:
                self.report({'WARNING'},
                            "SculptCore: anchored stroke must start on the surface")
                _draw._draw_counter_pop()
                self._close_generic()
                return {'CANCELLED'}
            self._anchor = a_hit[0]
            self._anchor_normal = a_hit[1]
            self._anchor_screen = (event.mouse_region_x, event.mouse_region_y)
            self._anchor_radius = self._base_radius(context, a_hit[0])
            # Anchored pins the dab center, so a snake-hook drag can only come
            # from the cursor: same plane projection the grab path uses, taken
            # at pen-down so the first dab's delta is exactly zero.
            if self._snake_hook:
                self._drag_origin = _cursor_on_anchor_plane(context, event, self._anchor)

        # Kernel toggles (smooth/mask) accumulate inherently, like vanilla,
        # and non-accumulate only exists where vanilla shows the option
        # (has_accumulate): for kernels without the concept — smooth is a
        # relaxation, not a displacement — the engine's snapshot re-basing
        # (nonAccum) is nonsense and blows the geometry up.
        accumulate = (self.mode in {'SMOOTH', 'MASK'}
                      or self._grab_class
                      or not self.brush.sculpt_capabilities.has_accumulate
                      or (self._generic.settings.value("sculptcore.brush.accumulate")
                          if self._generic else self.brush.use_accumulate)
                      or (not kernel_toggle and
                          self.brush.sculpt_brush_type in mapping.FORCE_ACCUMULATE))
        # The plane family's frame policy (sculpt_plane, the Original toggles,
        # the gather radii); a kernel toggle runs a kernel that reads none of
        # it. The view axis is per stroke, like vanilla's `view_normal`.
        plane_frame = None
        if not kernel_toggle:
            from ..brush_properties.stroke_settings import view_axis
            plane_frame = mapping.plane_frame(
                self.brush, self._generic.settings if self._generic else None,
                view_axis(context, ob))
        # Grids-native dispatch (multires W1): plain dab/grab strokes of
        # kernels the engine reports as grids-capable skip the materialized-mesh
        # hot path entirely, and so do autosmooth programs when every entry is
        # capable (E2; dyntopo never coexists with multires, so a program here is
        # autosmooth's). Snake hook rides this too — its per-dab state is written
        # on the shared Brush, which both paths read. Preview flows stay
        # mesh-path (the grid executor has no preview machinery).
        grids_kernel = None
        if (self.session.multires_ptr is not None
                and not self._preview_method
                and (self._program is None
                     or program_grids_capable(self.session, self.kernel))):
            grids_kernel = self.kernel
        # The grab-class path is the anchored one (fixed region at the stroke
        # start, absolute cursor drag); every other path dabs along the stroke.
        stroke_begin(self.session, has_dyntopo=self._dyntopo is not None,
                     accumulate=accumulate, anchored_grab=self._grab_class,
                     grids_kernel=grids_kernel,
                     cage_kernel=self.kernel if self._cage_smooth else None,
                     plane_frame=plane_frame)
        # The grids session is created inside stroke_begin, so its own copy of
        # the view matrix can only be pushed here — the mesh-path push above
        # rides the long-lived executor.
        if self.session.last_stroke_grids and texture.needs_render_matrix(self.brush):
            texture.apply_render_matrix_grids(context, self.session.grid_ptr)
        # First dab at the invoke location — before the modal handler is
        # registered, so an engine-refused first batch can still bail out with
        # a plain CANCELLED return.
        self._publish_cursor_pressure(event.pressure)
        if self._preview_method:
            self._dab_preview(context, event)
        else:
            self._dab_at(context, event)
        if self._engine_dead:
            self.report({'WARNING'}, "SculptCore: engine refused the stroke; see the system console")
            if self._preview_method:
                return self._finish_preview(context, commit=False)
            return self._finish(context, 'CANCELLED')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context, status):
        ob = context.active_object
        _draw._draw_counter_pop()
        cursor.set_size_scale(1.0)
        # On commit, flush the trailing spline segment held back by the
        # 1-segment lookahead (right-clamped); cancel drops it.
        if status == 'FINISHED' and not self._grab_class:
            points = self._spacer.flush(self._last_spacing)
            if self._batch:
                if points and not self._engine_dead:
                    self._apply_batch(context, points)
            else:
                for point, sample in points:
                    self._apply_spaced_dab(context, point, sample)
        if self._engine_dead:
            status = 'CANCELLED'
        stroke_end(self.session)
        self._close_generic()
        # Deferred write-back: with the draw provider active the viewport only
        # needs its GPU buffers; the Mesh ID syncs on demand through the
        # mode's flush callback (memfile encode / save / render). This keeps
        # stroke release free of the full Mesh (or MDISPS bake) write.
        if self.session.draw_key:
            convert.draw_refresh(ob)
        else:
            convert.flush(ob)
        # The stroke mutated geometry (dabs applied before release/cancel), so
        # push its delta-undo step regardless of finish vs cancel.
        undo.push(context, ob, self.session)
        self._publish_pivot(context, ob)
        # Every 3D viewport, not just the one the stroke ran in: the mid-stroke
        # cadence refreshes only the stroked region (like native sculpt), so
        # the others still show the pre-stroke surface until told otherwise
        # (vanilla's flush_update_done tags them all).
        _draw._tag_redraw_all_views(context)
        return {status}

    def _read_input(self, event):
        return self._input_sampler.read(
            event, (event.mouse_region_x, event.mouse_region_y), event.ctrl or self.mode == 'INVERT')

    def modal(self, context, event):
        if event.type in _draw._MOVE_EVENT_TYPES:
            # Blender never drops a queued pointer sample: when moves pile up
            # behind a busy main thread it retypes all but the newest of the run
            # to INBETWEEN_MOUSEMOVE (#wm_event_add_mousemove) and delivers them
            # all. Ignoring the inbetweens made the stroke jump straight to the
            # newest position, discarding exactly the hand motion the spacer
            # would have dabbed along -- the harder the scene, the more of the
            # stroke went missing. Native sculpt consumes them too, skipping
            # only the paint-cursor update (#paint_stroke_modal).
            live = event.type == 'MOUSEMOVE'
            if live:
                self._publish_cursor_pressure(event.pressure)
            if self._preview_method:
                self._dab_preview(context, event)
            else:
                # The backlog is sculpted but not presented per sample: the run
                # always ends on a live MOUSEMOVE, which carries the redraw for
                # the whole batch.
                self._dab_at(context, event, redraw=live)
            if self._engine_dead:
                self.report({'WARNING'}, "SculptCore: engine refused the stroke; see the system console")
                if self._preview_method:
                    return self._finish_preview(context, commit=False)
                return self._finish(context, 'CANCELLED')
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._preview_method:
                return self._finish_preview(context, commit=True)
            if not self._grab_class:
                self._dab_at(context, event, redraw=False)
            return self._finish(context, 'FINISHED')
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            if self._preview_method:
                return self._finish_preview(context, commit=False)
            return self._finish(context, 'CANCELLED')
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        """System-side teardown — window close or a forced modal cancel, where
        no release event will ever arrive. Same rollback path as ESC (the undo
        step still lands for whatever dabs applied); Blender ignores the
        return value here."""
        if self._preview_method:
            self._finish_preview(context, commit=False)
        else:
            self._finish(context, 'CANCELLED')


def register():
    bpy.utils.register_class(SCULPTCORE_OT_brush_stroke)


def unregister():
    bpy.utils.unregister_class(SCULPTCORE_OT_brush_stroke)
