# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Anchored / Drag-Dot preview-dab application: the mixin backing the
non-compounding preview-bracket path of ``SCULPTCORE_OT_brush_stroke``."""

from .. import brush_policy, convert, cursor, engine, mapping, symmetry, undo
from . import _draw
from .dab import apply_dab, apply_dab_program, preflight_preview, set_snake_hook_state
from .dyntopo import _refresh_queries
from .raycast import _cursor_on_anchor_plane, _pixel_to_world_length, _ray_origin_dir, raycast
from .session import _ensure_executor, set_image_sign, stroke_end
from ._util import _float3


class _PreviewMixin:
    """Preview-bracket dab application for the ANCHORED / DRAG_DOT stroke
    methods: one live dab per input, rolled back and re-applied so successive
    samples never compound."""

    def _preview_apply_image(self, center, normal, world_radius, extend,
                             snake_delta=None, view_sign=(1, 1, 1)):
        """Snapshot one dab image's region into the open preview session
        (``begin`` for the primary, ``extend`` for each mirror), then deform it.
        Snapshotting before the deform lets the whole group roll back together.
        No dyntopo in the preview path (anchored/drag-dot deform only)."""
        if self._generic:
            self._generic.view_image(view_sign)
        if self._engine_dead:
            return
        set_image_sign(self.session, view_sign)
        if snake_delta is not None:
            set_snake_hook_state(self.session, center, snake_delta)
        mgr = engine.manager()
        executor = _ensure_executor(self.session)
        center_v = _float3(mgr, *center)
        # The snapshot must cover everything the dab will touch, so it takes the
        # dab's node-filter radius, not the falloff radius — a preview sized
        # smaller than an unbounded field would leave residue on rollback.
        preview_r = brush_policy.field_radius(
            self.kernel, world_radius, self.session.brush_obj)
        try:
            if extend:
                executor.extendPreviewDab(center_v, preview_r)
            else:
                executor.beginPreviewDab(center_v, preview_r)
        finally:
            center_v.dispose()
        if self._program is not None:
            moved = apply_dab_program(self.session, self._program, center, normal,
                                     world_radius, kernel=self.kernel, grab_add=extend)
        else:
            moved = apply_dab(self.session, self.kernel, center, normal, world_radius, grab_add=extend)
        if moved < 0:
            self._engine_dead = True

    def _dab_preview(self, context, event):
        """Anchored / Drag-Dot: one live dab (plus mirrors) inside a preview
        bracket so successive inputs never compound. Resolve the new dab first,
        then roll back the previous provisional group and apply the new one."""
        sample = self._read_input(event)
        if sample is None:
            return
        sample.upload(self.session.brush_obj)
        invert = sample.invert
        executor = _ensure_executor(self.session)
        coord = (event.mouse_region_x, event.mouse_region_y)

        if self._stroke_method == 'ANCHORED':
            # Dab pinned at the anchor; radius grows with screen-space drag.
            center = self._anchor
            normal = self._anchor_normal
            import mathutils
            drag_px = (mathutils.Vector(coord)
                       - mathutils.Vector(self._anchor_screen)).length
            # Radius is the unprojected drag length (0 at the anchor, growing as
            # the cursor pulls away); check `is None` so a genuine 0 is kept.
            world_radius = _pixel_to_world_length(context, center, drag_px)
            if world_radius is None:
                world_radius = self._anchor_radius
        else:  # DRAG_DOT: one dab at the live cursor.
            origin, direction = _ray_origin_dir(context, coord)
            hit = raycast(self.session, origin, direction)
            if hit is None:
                # Cursor off the surface: keep the previous provisional dab.
                return
            center, normal, _ = hit
            world_radius = self._base_radius(context, center)
            if self._snake_hook and self._preview_origin is None:
                self._preview_origin = center

        # A preview dab is rolled back and re-applied from the same base on
        # every input, so snake hook's drag is the whole drag since the stroke
        # start (vanilla's anchored grab-delta branch), not the step since the
        # last input. Anchored pins the center, so its drag comes from the
        # cursor plane point; drag-dot's center moves with the cursor.
        snake_delta = None
        if self._snake_hook:
            if self._stroke_method == 'ANCHORED':
                plane_point = _cursor_on_anchor_plane(context, event, self._anchor)
                snake_delta = tuple(plane_point[i] - self._drag_origin[i] for i in range(3))
            else:
                snake_delta = tuple(center[i] - self._preview_origin[i] for i in range(3))

        generic_payload = None
        if self._generic:
            self._set_generic_view(context, center)
            generic_payload = self._prepare_generic(sample, world_radius)
            world_radius = generic_payload[0][1]
        unified = context.tool_settings.sculpt.unified_paint_settings
        if generic_payload is not None:
            self._publish_generic(generic_payload)
        elif self._smooth_stroke:
            # Smooth registers no engine dynamics (see invoke): fold pressure
            # into strength / radius Python-side through the baked LUTs.
            strength = self.brush.strength
            if unified.use_unified_strength:
                strength = unified.strength
            strength *= self._overlap
            if self._pressure_strength_lut is not None and sample.pressure is not None:
                strength *= mapping.eval_pressure_lut(self._pressure_strength_lut, sample.pressure)
            if self._pressure_size_lut is not None and sample.pressure is not None:
                world_radius *= mapping.eval_pressure_lut(self._pressure_size_lut, sample.pressure)
            mapping.apply_dab_state(self.brush, unified, self.session.brush_obj,
                                    world_radius=world_radius, invert=invert,
                                    strength_override=strength, allow_invert=False)
        else:
            mapping.apply_dab_state(self.brush, unified, self.session.brush_obj,
                                    world_radius=world_radius, invert=invert,
                                    strength_scale=self._overlap, allow_invert=True)
        # Roll back the previous provisional group only now that a new dab is
        # resolved (a drag-dot miss above leaves the last dab intact).
        if snake_delta is not None:
            set_snake_hook_state(self.session, center, snake_delta)
        valid = preflight_preview(self.session, self.kernel, self._program, center, normal)
        if not valid:
            self._engine_dead = True
            return
        if executor.previewActive():
            executor.rollbackPreviewDab()
            # The rollback moved verts back, so the node bounds are stale in the
            # other direction now — refresh before this tick's dab filters.
            _refresh_queries(self.session)
        # Only the last provisional dab survives the preview bracket, so the
        # pivot replaces rather than accumulates (an average over every input
        # would drag it back toward the stroke's first position).
        self._pivot_sum = list(center)
        self._pivot_n = 1
        self._preview_apply_image(center, normal, world_radius, extend=False,
                                  snake_delta=snake_delta)
        # Mirror images share the one preview bracket, so one rollback reverts
        # the whole group.
        for sign in self._mirror_signs:
            self._preview_apply_image(
                symmetry.reflect(center, sign), symmetry.reflect(normal, sign),
                world_radius, extend=True,
                snake_delta=None if snake_delta is None else symmetry.reflect(snake_delta, sign), view_sign=sign)
        self._mid_redraw(context)

    def _finish_preview(self, context, commit):
        """End an anchored / drag-dot stroke: commit keeps the one live dab and
        pushes an undo step; cancel rolls it back and pushes nothing (the mesh
        is left exactly as the stroke began)."""
        ob = context.active_object
        _draw._draw_counter_pop()
        cursor.set_size_scale(1.0)
        executor = _ensure_executor(self.session)
        if executor.previewActive():
            if commit:
                executor.commitPreviewDab()
            else:
                executor.rollbackPreviewDab()
        stroke_end(self.session)
        self._close_generic()
        if self.session.draw_key:
            convert.draw_refresh(ob)
        else:
            convert.flush(ob)
        if commit:
            undo.push(context, ob, self.session)
            # A rolled-back preview left the mesh as the stroke found it, so it
            # gets no say in the pivot.
            self._publish_pivot(context, ob)
        if context.area:  # absent on cancel() teardown (window close)
            context.area.tag_redraw()
        return {'FINISHED' if commit else 'CANCELLED'}

    def _publish_cursor_pressure(self, pressure):
        """Scale the viewport cursor circle by the current size-pressure factor
        so it tracks the pen like the deformation does (1.0 when size pressure
        is off)."""
        if self._generic:
            return
        scale = 1.0
        if self._pressure_size_lut is not None:
            scale = mapping.eval_pressure_lut(self._pressure_size_lut, pressure)
        cursor.set_size_scale(scale)
