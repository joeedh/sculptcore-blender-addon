# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Generic (non-preview) dab application: the mixin backing the spaced,
grab and batched dab paths of ``SCULPTCORE_OT_brush_stroke``."""

from .. import convert, engine, mapping, symmetry, undo
from ..brush_properties import shift_smooth
from ..brush_properties.adapters import STRENGTH
from . import _draw
from .dab import apply_dab, apply_dab_program, apply_grab_dab, set_snake_hook_state
from .dyntopo import (DYNTOPO_EDGE_MIN_FACTOR, apply_dyntopo_dab, build_dyntopo_params,
                      dyntopo_due, smooth_iteration_strengths)
from .raycast import (_coord_on_plane, _cursor_on_anchor_plane, _ray_from_event,
                      _ray_origin_dir, _world_radius, raycast)
from .session import _ensure_brush, _ensure_executor, set_image_sign


class _GenericApplyMixin:
    """Plain/grab/batched dab application and its supporting per-stroke state
    (pivot tracking, mid-stroke refresh, generic-property payload prep)."""

    def _dab_at(self, context, event, redraw=True):
        """Apply the stroke at one pointer sample. `redraw` off skips the
        viewport tail — used for the backlog samples of one event batch, which
        are sculpted but not individually presented (see ``modal``)."""
        sample = self._read_input(event)
        if sample is None:
            return
        paint = context.tool_settings.sculpt
        unified = paint.unified_paint_settings
        # The keymap sets INVERT for Ctrl-LMB; live Ctrl also inverts so the
        # direction can be toggled mid-stroke.
        invert = event.ctrl or self.mode == 'INVERT'

        if self._grab_class:
            sample.upload(self.session.brush_obj)
            if self._anchor is None:
                # Anchor the region at the stroke-start surface point. Only the
                # anchoring dab needs the surface; misses just retry next move.
                hit = _ray_from_event(context, event, self.session)
                if hit is None:
                    return
                position, normal, _face = hit
                self._anchor = position
                self._anchor_normal = normal
                self._anchor_radius = self._base_radius(context, position)
                # Drag reference: the mouse ray's plane projection at pen-down,
                # so both drag endpoints come from the same projection and the
                # first dab's delta is exactly zero, not merely near it.
                self._drag_origin = _cursor_on_anchor_plane(context, event, self._anchor)
            # No re-raycast after anchoring: the drag must keep working when
            # the cursor leaves the surface (vanilla grab semantics), and the
            # region/radius stay pinned to the stroke start regardless.
            if not self._generic:
                mapping.apply_dab_state(self.brush, unified, self.session.brush_obj,
                                        world_radius=self._anchor_radius, invert=invert,
                                        strength_scale=self._overlap)
            active_radius = self._anchor_radius
            if self._generic:
                self._set_generic_view(context, self._anchor)
                payload = self._prepare_generic(sample, self._anchor_radius)
                self._publish_generic(payload)
                active_radius = payload[0][1]
            # Drag target = anchor + mouse motion on the view-facing plane
            # through the anchor (both endpoints are projections of the mouse
            # ray, so the first dab's delta is exactly zero).
            plane_point = _cursor_on_anchor_plane(context, event, self._anchor)
            drag = mapping.drag_offset(
                self.brush,
                tuple(plane_point[i] - self._drag_origin[i] for i in range(3)),
                self._anchor_normal, self.session.brush_obj.strength)
            cursor = tuple(self._anchor[i] + drag[i] for i in range(3))
            self._track_pivot(cursor)
            if apply_grab_dab(self.session, self.kernel, self._anchor, cursor,
                              self._anchor_normal, active_radius) < 0:
                self._engine_dead = True
                return
            # Symmetry: reflect the anchor, cursor and normal directly (no
            # re-raycast for grab — the resolved plane point is used as-is).
            for sign in self._mirror_signs:
                if self._generic:
                    self._generic.view_image(sign)
                moved = apply_grab_dab(
                    self.session, self.kernel,
                    symmetry.reflect(self._anchor, sign),
                    symmetry.reflect(cursor, sign),
                    symmetry.reflect(self._anchor_normal, sign),
                    active_radius, accum_add=True)
                if moved < 0:
                    self._engine_dead = True
                    return
        else:
            if self._generic:
                hit = _ray_from_event(context, event, self.session)
                pixel_r = self._pixel_radius(context, hit[0] if hit is not None else (0, 0, 0))
                spacing = self._generic.settings.value('sculptcore.brush.spacing', sample.channels)
            else:
                pixel_r = mapping.pixel_radius(context.tool_settings.sculpt, self.brush)
                spacing = self.brush.spacing
            step = max(spacing, 1) / 50.0 * pixel_r
            coord = (event.mouse_region_x, event.mouse_region_y)
            # Remember the last-move state so the trailing spline segment can be
            # flushed on release (the release event carries no spline context).
            self._last_invert = invert
            self._last_pressure = event.pressure
            self._last_spacing = step
            points = self._spacer.add(coord, step, sample)
            if self._batch:
                if points and not self._engine_dead:
                    self._apply_batch(context, points)
            else:
                for point, dab_sample in points:
                    self._apply_spaced_dab(context, point, dab_sample)

        # Face sets and colour are cage attributes a subdivided level only
        # mirrors, so this batch's paint is carried onto the cage and the grids
        # it touched are re-derived from it -- now, not at stroke end, or the
        # stroke would draw at grid resolution and then snap to the cage's on
        # release (§6.3 of plans/grid-domain-attributes.md).
        if self.session.multires_ptr and not self.session.last_stroke_cage:
            undo.scatter_cage_columns(self.session)
        if redraw:
            self._mid_redraw(context)

    def _mid_redraw(self, context):
        """Throttled mid-stroke refresh: the draw provider needs only its GPU
        buffers refreshed; the Mesh write-back is deferred to the mode's flush
        callback. The full flush remains only for the no-provider fallback,
        where the viewport draws the Mesh itself."""
        import time
        now = time.monotonic()
        # Cadence: wall-clock throttle AND a frame consumed the last refresh.
        # Above 30 fps the frame gate never engages (a frame always presents
        # between two 33 ms throttle passes); it sheds refreshes only when
        # events outrun frames — event floods and frame-bound heavy scenes —
        # where a refill no frame reads is provably wasted work.
        if (now - self._last_flush > 1.0 / 30.0
                and _draw._frames_presented != self._flush_frame):
            # Deferred grids normals resolve at the same cadence the provider
            # re-uploads, so shading and geometry stay in step.
            if self.session.last_stroke_grids and self.session.grid_ptr:
                engine.capi().lib.GridStroke_flushNormals(self.session.grid_ptr)
            if self.session.draw_key:
                convert.draw_refresh(context.active_object)
            else:
                convert.flush(context.active_object)
            self._last_flush = now
            self._flush_frame = _draw._frames_presented
        # Region, not area: area.tag_redraw() would redraw every region of the
        # View3D area per event -- header, toolbar, sidebar and the brush asset
        # shelf, whose preview icons re-upload and re-mip ~10 textures a frame
        # (immDrawPixels creates them from scratch). Native sculpt tags only
        # the drawing region; match it.
        context.region.tag_redraw()

    def _track_pivot(self, position):
        """Fold one logical dab's object-space center into the stroke's running
        pivot sum (see ``_publish_pivot``)."""
        for i in range(3):
            self._pivot_sum[i] += position[i]
        self._pivot_n += 1

    def _publish_pivot(self, context, ob):
        """Hand the stroke's average center to Blender as the orbit pivot.

        ``view3d_orbit_calc_center`` reads it back through
        ``BKE_paint_stroke_get_average`` for a custom mode that declares
        ``bl_use_sculpt_paint``, so "Orbit Around Selection" follows the last
        stroke instead of sitting at the object origin. World space, because
        that is what the Paint runtime stores."""
        if not self._pivot_n:
            return
        import mathutils
        mean = mathutils.Vector(self._pivot_sum) / self._pivot_n
        context.tool_settings.sculpt.stroke_pivot = ob.matrix_world @ mean

    def _apply_one_image(self, position, normal, world_radius, due, snake_delta=None, view_sign=(1, 1, 1)):
        """Apply one dab image (primary or a symmetry mirror) through the active
        path — plain, autosmooth-program, or dyntopo. Each image gets a unique
        monotonic seed (dyntopo independent-set selection). ``snake_delta`` is
        this image's drag step for the snake-hook kernel (already reflected for
        a mirror image); None for every other brush."""
        if self._generic:
            self._generic.view_image(view_sign)
        if self._engine_dead:
            return
        set_image_sign(self.session, view_sign)
        self._dab_count += 1
        seed = self._dab_count
        if self.session.multires_ptr and not self.session.last_stroke_cage:
            # The region this dab paints, for the per-dab cage collapse: a dab
            # smaller than a base face moves no cage vert, so the collapse has
            # no other way to learn which grids to re-derive (see
            # undo.scatter_cage_columns). Grab-class dabs skip this path and
            # never write an attribute; cage-dab strokes write the cage
            # directly, so there is nothing to collapse.
            self.session.dab_regions.extend(
                (position[0], position[1], position[2], world_radius))
        if snake_delta is not None:
            set_snake_hook_state(self.session, position, snake_delta)
        if self._dyntopo is not None:
            moved = apply_dyntopo_dab(self.session, self._program, position, normal,
                                     world_radius, self._dyntopo if due else None, seed)
        elif self._program is not None:
            moved = apply_dab_program(self.session, self._program, position, normal,
                                     world_radius, kernel=self.kernel)
        else:
            moved = apply_dab(self.session, self.kernel, position, normal, world_radius)
        if moved < 0:
            self._engine_dead = True

    def _snake_hook_advance(self, context, point):
        """The snake-hook dab center and drag step for one spacer-emitted point,
        as ``(center, delta)``; None while the stroke has yet to find a surface
        to start from.

        Vanilla decouples this brush from the surface after the first dab
        (sculpt.cc ``brush_delta_update`` / ``stroke_cache_update``): the center
        is seeded from the stroke's first hit and thereafter advanced only by the
        previous dab's delta, never re-read from the sample under the cursor. So
        the influence region walks out with the extruded tip instead of snapping
        back to whatever surface the cursor still points at — and the stroke
        keeps working once the tip has left the mesh entirely. The cursor
        contributes only the step, measured on the view-facing plane through the
        seed point (vanilla's ``orig_grab_location`` depth)."""
        if self._sh_center is None:
            origin, direction = _ray_origin_dir(context, point)
            hit = raycast(self.session, origin, direction)
            if hit is None:
                return None  # nothing to hook yet; the next sample retries
            position, normal, _face = hit
            self._sh_origin = position
            self._sh_normal = normal
            self._sh_center = position
            self._sh_plane = _coord_on_plane(context, point, position)
            self._sh_delta = (0.0, 0.0, 0.0)
            return position, self._sh_delta
        # Advance by the *previous* step before measuring the new one, so the
        # region trails the tip by one dab exactly as vanilla's cache does.
        center = tuple(self._sh_center[i] + self._sh_delta[i] for i in range(3))
        plane = _coord_on_plane(context, point, self._sh_origin)
        delta = tuple(plane[i] - self._sh_plane[i] for i in range(3))
        self._sh_center = center
        self._sh_plane = plane
        self._sh_delta = delta
        return center, delta

    def _close_generic(self):
        if self._generic is not None:
            self._generic.close()
            self.session.generic_runtime = None
            self._generic = None

    def _base_radius(self, context, position):
        if self._generic is None:
            return _world_radius(context, self.brush, position)
        from ..brush_properties.stroke_settings import object_radius
        return object_radius(context, self._generic.settings.size, position)

    def _pixel_radius(self, context, position=(0, 0, 0)):
        if self._generic is None:
            return mapping.pixel_radius(context.tool_settings.sculpt, self.brush)
        from ..brush_properties.stroke_settings import pixel_radius
        return pixel_radius(context, self._generic.settings.size, position)

    def _set_generic_view(self, context, position):
        from ..brush_properties.stroke_settings import view_direction
        self._generic.view_direction = view_direction(context, position)
        self._generic.view_image()

    def _prepare_generic(self, sample, base_radius):
        row = self._generic.evaluate([sample], [base_radius])[0]
        payload = self._generic.prepare(
            row, sample, family_scale=self._family_scale, allow_invert=not self._smooth_stroke,
            strength_identifier=shift_smooth.STRENGTH if self._shift_smooth else STRENGTH,
            extras=self._toggle_extras)
        if base_radius > 0:
            self._generic.cursor_scale = payload[0][1] / base_radius
        return payload

    def _publish_generic(self, payload, strength_override=None):
        self._generic.publish(payload, program=self._program,
                              smooth_command=self._generic_smooth_command,
                              strength_override=strength_override)

    def _apply_spaced_dab(self, context, point, sample):
        """Resolve one spacer-emitted 2D point to a dab center — the surface hit
        under it, or for snake hook the advancing tip center — and apply the
        primary dab plus one reflected dab per symmetry mirror."""
        if self._engine_dead:
            return
        invert, pressure = sample.invert, sample.pressure
        sample.upload(self.session.brush_obj)
        snake_delta = None
        if self._snake_hook:
            advance = self._snake_hook_advance(context, point)
            if advance is None:
                return
            position, snake_delta = advance
            # No hit to sample once the region has walked off the surface, so
            # the seed normal stands for the stroke. (Vanilla recomputes an area
            # normal from the affected verts instead — and freezes it outright
            # when normal_weight > 0.)
            normal = self._sh_normal
        else:
            origin, direction = _ray_origin_dir(context, point)
            hit = raycast(self.session, origin, direction)
            if hit is None:
                return
            position, normal, _face = hit
        world_radius = self._base_radius(context, position)
        generic_payload = None
        if self._generic:
            self._set_generic_view(context, position)
            generic_payload = self._prepare_generic(sample, world_radius)
            world_radius = generic_payload[0][1]
        self._track_pivot(position)
        unified = context.tool_settings.sculpt.unified_paint_settings
        # Advance the stroke arc length and decide the dyntopo cadence once per
        # logical dab, so every mirror image remeshes on the same samples
        # (a per-image decision would let the primary starve the mirrors).
        self._stroke_s += self._last_spacing
        due = (self._dyntopo is not None
               and dyntopo_due(self._stroke_s, self._last_dyntopo_s, self._dyntopo_spacing))
        if due:
            self._last_dyntopo_s = self._stroke_s
            if self._detail_factor is not None:
                # RELATIVE/BRUSH detail scales with the (depth-dependent)
                # world radius; refresh the bounds for this remesh pass.
                l_max = self._detail_factor * world_radius
                build_dyntopo_params(self.session, l_max,
                                     l_max * DYNTOPO_EDGE_MIN_FACTOR)

        if self._smooth_stroke:
            # Multi-pass smooth (vanilla semantics): strength maps to N
            # relaxation passes at explicit per-pass strengths. Pressure and the
            # overlap factor fold into the base Python-side (smooth registers no
            # engine dynamics — see invoke); the pressure factor comes from the
            # baked curve_strength / curve_size response LUTs.
            if generic_payload is not None:
                strength = generic_payload[0][0]
            else:
                strength = unified.strength if unified.use_unified_strength else self.brush.strength
                if self._pressure_strength_lut is not None and pressure is not None:
                    strength *= mapping.eval_pressure_lut(self._pressure_strength_lut, pressure)
                if self._pressure_size_lut is not None and pressure is not None:
                    world_radius *= mapping.eval_pressure_lut(self._pressure_size_lut, pressure)
                strength *= self._overlap
            for pass_strength in smooth_iteration_strengths(strength, self._smooth_strength_max):
                # Smoothing has no inverse (see apply_dab_state): ignore Ctrl
                # and the brush direction for the smooth passes.
                if generic_payload is not None:
                    self._publish_generic(generic_payload, pass_strength)
                else:
                    mapping.apply_dab_state(self.brush, unified, self.session.brush_obj,
                                            world_radius=world_radius, invert=False,
                                            strength_override=pass_strength,
                                            allow_invert=False)
                self._apply_one_image(position, normal, world_radius, due,
                                      snake_delta=snake_delta)
                for sign in self._mirror_signs:
                    self._apply_one_image(
                        symmetry.reflect(position, sign),
                        symmetry.reflect(normal, sign), world_radius, due,
                        snake_delta=(None if snake_delta is None
                                     else symmetry.reflect(snake_delta, sign)), view_sign=sign)
                due = False  # remesh at most once per logical dab
            return

        if generic_payload is not None:
            self._publish_generic(generic_payload)
        else:
            mapping.apply_dab_state(self.brush, unified, self.session.brush_obj,
                                    world_radius=world_radius, invert=invert, strength_scale=self._overlap)
        self._apply_one_image(position, normal, world_radius, due,
                              snake_delta=snake_delta)
        # Symmetry mirror images: reflect the resolved primary center and normal
        # directly (mirror the operation, as vanilla sculpt does), reusing the
        # primary's world radius. Re-raycasting the mirrored view ray instead —
        # as the reference app does — is only equivariant where the mirrored
        # surface is identical and the mirrored ray hits at all; reflecting the
        # resolved hit is exact and cannot drop a mirror image.
        for sign in self._mirror_signs:
            self._apply_one_image(
                symmetry.reflect(position, sign),
                symmetry.reflect(normal, sign), world_radius, due,
                snake_delta=(None if snake_delta is None
                             else symmetry.reflect(snake_delta, sign)), view_sign=sign)

    def _apply_generic_batches(self, dabs, inputs, payloads, grids, directions):
        """Keep order while batching rows with identical converted command settings."""
        session, lib = self.session, engine.capi().lib
        keys = [(payload[0][0], payload[0][2:5], payload[1], payload[2], direction)
                for payload, direction in zip(payloads, directions)]
        start = 0
        while start < len(payloads):
            end = start + 1
            while end < len(payloads) and keys[end] == keys[start]:
                end += 1
            self._generic.view_direction = directions[start]
            self._generic.view_image()
            self._publish_generic(payloads[start])
            count = end - start
            batch, channels = dabs[start:end], inputs[start:end]
            strength = payloads[start][0][0]
            self._dab_count += count * (1 + len(self._mirror_signs))
            if grids:
                if self._program is not None:
                    moved = lib.GridStroke_dabBatchProgramInputs(
                        session.grid_ptr, self._program.ptr, count, batch, strength, channels,
                        self._mirror_flat, len(self._mirror_signs), 1)
                else:
                    moved = lib.GridStroke_dabBatchInputs(
                        session.grid_ptr, int(self.kernel), count, batch, strength, channels,
                        self._mirror_flat, len(self._mirror_signs), 1)
            else:
                function = (lib.MeshStroke_dabBatchProgramInputs if self._program is not None
                            else lib.MeshStroke_dabBatchInputs)
                target = self._program.ptr if self._program is not None else int(self.kernel)
                moved = function(_ensure_executor(session).ptr, session.tree().ptr, session.mesh().ptr,
                                 _ensure_brush(session).ptr, target, count, batch, strength, channels,
                                 self._filter_mul, self._mirror_flat, len(self._mirror_signs), 1)
            if moved < 0:
                self._engine_dead = True
                return
            start = end

    def _apply_batch(self, context, points):
        """The C++ dab loop (``sculptcore_cpp_dab_loop``): resolve and apply
        every spacer-emitted point of one pointer event in two flat engine
        calls — a batch raycast and a dab batch — instead of one Python
        round-trip per dab. Ray synthesis and the post-cast world radius use
        the exact math of ``_apply_spaced_dab``; the engine side runs the same
        prop-write / device-refill / apply / symmetry cycle per dab (see
        ``GridStroke_dabBatch`` / ``MeshStroke_dabBatch``). A negative return
        is the engine's stroke-dead sentinel (stale grids domain, §7 of the
        design): flag it and let invoke/modal tear the stroke down — never
        fall back to the Python path mid-stroke."""
        import numpy as np

        session = self.session
        lib = engine.capi().lib
        n = len(points)
        rays = np.empty((n, 6), dtype=np.float32)
        for i, (point, sample) in enumerate(points):
            origin, direction = _ray_origin_dir(context, point)
            rays[i, 0:3] = origin
            rays[i, 3:6] = direction
        hits = np.zeros((n, 6), dtype=np.float32)
        hit_mask = np.zeros(n, dtype=np.uint8)
        grids = bool(session.last_stroke_grids and session.grid_ptr)
        if grids:
            hit_count = lib.GridStroke_castBatch(
                session.grid_ptr, n, rays, hits, hit_mask)
        else:
            hit_count = lib.MeshStroke_castBatch(
                session.tree().ptr, n, rays, hits, hit_mask)
        if hit_count < 0:
            self._engine_dead = True
            return
        if hit_count == 0:
            return
        # Per logical dab: the depth-dependent world radius (the one per-dab
        # quantity Python still owns — it needs the region/view matrices) and
        # the pivot fold, primaries only, as the per-dab path does.
        dabs = np.empty((hit_count, 7), dtype=np.float32)
        inputs = np.empty((hit_count, 6), dtype=np.float32)
        row = 0
        samples = []
        for i in range(n):
            if not hit_mask[i]:
                continue
            position = (float(hits[i, 0]), float(hits[i, 1]), float(hits[i, 2]))
            self._track_pivot(position)
            dabs[row, 0:6] = hits[i]
            dabs[row, 6] = self._base_radius(context, position)
            sample = points[i][1]
            samples.append(sample)
            inputs[row, :5] = sample.batch_row()
            inputs[row, 5] = sample.invert ^ (self._generic.settings.subtract if self._generic
                                                  else self.brush.direction == 'SUBTRACT')
            row += 1
        payloads = None
        if self._generic:
            rows = self._generic.evaluate(samples, dabs[:, 6])
            payloads = [self._generic.prepare(values, sample, family_scale=self._family_scale)
                        for values, sample in zip(rows, samples)]
            if dabs[-1, 6] > 0:
                self._generic.cursor_scale = payloads[-1][0][1] / float(dabs[-1, 6])
            for index, payload in enumerate(payloads):
                dabs[index, 6] = payload[0][1]
        if session.multires_ptr:
            # The regions this batch paints, for the per-dab cage collapse (see
            # undo.scatter_cage_columns). The mirror images are applied engine
            # side, so reflect them here -- the collapse needs every sphere the
            # kernel wrote into, not just the primaries.
            for i in range(hit_count):
                centre = (float(dabs[i, 0]), float(dabs[i, 1]), float(dabs[i, 2]))
                radius = float(dabs[i, 6])
                session.dab_regions.extend(centre + (radius,))
                for sign in self._mirror_signs:
                    session.dab_regions.extend(
                        tuple(symmetry.reflect(centre, sign)) + (radius,))
        # Strength/invert exactly as mapping.apply_dab_state folds them; both
        # are constant across the event's batch (pressure reaches strength
        # through the engine's device dynamics, not this scalar).
        if payloads is not None:
            from ..brush_properties.stroke_settings import view_direction
            directions = [view_direction(context, row[:3]) for row in dabs]
            self._apply_generic_batches(dabs, inputs, payloads, grids, directions)
            return
        unified = context.tool_settings.sculpt.unified_paint_settings
        strength = (unified.strength if unified.use_unified_strength
                    else self.brush.strength) * self._overlap
        self._dab_count += hit_count * (1 + len(self._mirror_signs))
        if grids and self._program is not None:
            moved = lib.GridStroke_dabBatchProgramInputs(
                session.grid_ptr, self._program.ptr, hit_count, dabs,
                strength, inputs,
                self._mirror_flat, len(self._mirror_signs), 2)
        elif grids:
            moved = lib.GridStroke_dabBatchInputs(
                session.grid_ptr, int(self.kernel), hit_count, dabs,
                strength, inputs,
                self._mirror_flat, len(self._mirror_signs), 2)
        elif self._program is not None:
            moved = lib.MeshStroke_dabBatchProgramInputs(
                _ensure_executor(session).ptr, session.tree().ptr,
                session.mesh().ptr, _ensure_brush(session).ptr,
                self._program.ptr, hit_count, dabs,
                strength, inputs,
                self._filter_mul, self._mirror_flat, len(self._mirror_signs), 2)
        else:
            moved = lib.MeshStroke_dabBatchInputs(
                _ensure_executor(session).ptr, session.tree().ptr,
                session.mesh().ptr, _ensure_brush(session).ptr,
                int(self.kernel), hit_count, dabs,
                strength, inputs,
                self._filter_mul, self._mirror_flat, len(self._mirror_signs), 2)
        if moved < 0:
            self._engine_dead = True
