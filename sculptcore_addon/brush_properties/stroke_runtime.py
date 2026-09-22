# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Checked transfer of native-evaluated semantic settings to an active engine brush."""
from .adapters import CAVITY, SIZE, STRENGTH
from .evaluation import to_engine
from .legacy import ASSOCIATIONS
from .native_evaluation import NativeEvaluation, native_layers
from .registry import PropertyError
from .stroke_settings import PREFIX


class StrokeRuntime:
    def __init__(self, settings, session, kernel):
        from .. import engine, stroke
        from sculptcore.brush_properties import CommonProperties
        self.settings, self.session, self.kernel = settings, session, int(kernel)
        self.manager = engine.manager()
        self.executor = stroke._ensure_executor(session)
        self.brush = session.brush_obj
        self.native = NativeEvaluation(settings)
        self.common = CommonProperties(self.manager, self.brush)
        self.access = None
        self._last = None
        self._overlaps = {}
        self.cursor_scale = 1.0
        self._command_stack_key = None
        self.view_direction = (0, 0, -1)
        try:
            self._uniforms()
            for index in range(6):
                self.common.clear_stack(index)
            for uniform in self.access.uniforms:
                if uniform.dynamic:
                    self.access.clear_stack(uniform.index)
            self._install_constants()
        except BaseException:
            self.close()
            raise

    def _uniforms(self):
        from sculptcore.brush_properties import UniformProperties
        if self.access is None or self.access.token != self.executor.uniformQueryToken():
            self.access = UniformProperties(self.manager, self.executor, self.kernel)
            self.by_name = {item.name: item for item in self.access.uniforms}
        return self.access

    def _install_constants(self):
        from .. import mapping
        settings, brush = self.settings, self.brush
        cache = self.session.curve_cache
        mapping._upload_lut(cache, 'falloff', settings.falloff.samples, brush)
        brush.falloff_kind = 3
        mapping.apply_falloff_shape(brush, settings.brush_type, settings.tip_scale_x, settings.tip_roundness)
        brush.automask_cavity = (settings.value(CAVITY + '.use_automasking_cavity')
                                or settings.value(CAVITY + '.use_automasking_cavity_inverted'))
        for native, identifier in (
                ('cavity_inverted', CAVITY + '.use_automasking_cavity_inverted'),
                ('cavity_use_curve', CAVITY + '.use_automasking_custom_cavity_curve'),
                ('cavity_factor', CAVITY + '.cavity_factor'),
                ('cavity_blur_steps', CAVITY + '.cavity_blur_steps'),
                ('automask_view_normal', PREFIX + 'automask_view_normal'),
                ('view_normal_limit', PREFIX + 'view_normal_limit'),
                ('view_normal_falloff', PREFIX + 'view_normal_falloff'),
                ('cull_backfaces', PREFIX + 'cull_backfaces')):
            setattr(brush, native, settings.value(identifier))
        if settings.cavity is not None:
            mapping._upload_lut(cache, 'cavity', settings.cavity.samples, brush)

    def evaluate(self, samples, radii):
        return self.native.evaluate([sample.batch_row() for sample in samples], radii)

    def values(self, row):
        values = {}
        for item, value in zip(self.settings.properties, row, strict=True):
            identifier = item.definition.identifier
            kind = self.settings._evaluator(identifier)._domain[0]
            values[identifier] = {'FLOAT32': float, 'INT32': int, 'BOOL': bool}[kind](value)
        return values

    def prepare(self, row, sample, *, family_scale=1.0, allow_invert=True, strength_identifier=STRENGTH,
                extras=None):
        """Build a complete immutable payload before changing any native setting.

        ``strength_identifier`` names the evaluated scalar that becomes the dab
        strength -- the brush strength, or the Shift-smooth strength on a
        smooth-toggle stroke. ``extras`` replaces the kernel scalars derived
        from the brush's own settings with an explicit ``(uniform, value)``
        sequence; a toggle stroke runs a kernel the active brush does not own,
        so its scalars come from the toggle's settings instead."""
        values = self.values(row)
        spacing = values[PREFIX + 'spacing']
        if spacing not in self._overlaps:
            self._overlaps[spacing] = self.settings.overlap(sample.channels)
        scale = self._overlaps[spacing] * family_scale
        strength = to_engine(STRENGTH, values[strength_identifier], strength_scale=scale)
        invert = bool(sample.invert ^ self.settings.subtract) if allow_invert else False
        plane_offset = values[PREFIX + 'plane_offset']
        plane = None
        if self.settings.brush_type == 'PLANE' and extras is None:
            # The plane brush's inversion, as mapping.apply_dab_state applies
            # it: the offset flips sign, Swap trades the reaches and runs the
            # kernel forward, Invert Displacement halves the strength.
            height, depth = values[PREFIX + 'plane_height'], values[PREFIX + 'plane_depth']
            if invert:
                plane_offset = -plane_offset
                if self.settings.plane_swap:
                    height, depth, invert = depth, height, False
                else:
                    strength *= 0.5
            plane = (('planeHeight', float(height)), ('planeDepth', float(depth)))
        common = (strength, values[SIZE], values[PREFIX + 'autosmooth'],
                  plane_offset, to_engine(PREFIX + 'spacing', spacing), invert)
        if extras is None:
            extras = self._brush_extras(values)
            if plane is not None:
                extras = (*extras, *plane)
        # The chained command inherits the strength stack and overrides its base.
        factor = values[PREFIX + 'autosmooth']
        return common, tuple(extras), factor

    def _brush_extras(self, values):
        """The kernel scalars the active brush's own settings drive."""
        from .shift_smooth import RAKE
        extras = []
        for identifier, (kernel, name) in ASSOCIATIONS.items():
            if kernel == self.settings.kernel_name and identifier in values:
                extras.append((name, values[identifier]))
        if self.settings.kernel_name == 'FEATURE_ALIGN':
            # The feature-align brush: its rake, and the smooth projection the
            # bsmooth row already exposes for every brush (both kernels read the
            # same engine field).
            extras.append(('rake', values[RAKE]))
            extras.append(('projection', values['sculptcore.kernel.bsmooth.projection']))
        if self.settings.brush_type == 'DRAW_SHARP':
            extras.append(('pinch', 0.0))
        elif self.settings.brush_type == 'PINCH':
            extras.append(('pinch', self.settings.local_strength))
        elif self.settings.brush_type == 'SNAKE_HOOK':
            extras.append(('pinch', to_engine(PREFIX + 'snake_pinch', values[PREFIX + 'snake_pinch'])))
        elif self.settings.brush_type in ('CREASE', 'BLOB'):
            # The crease kernel's signed square (mapping._MAP CREASE/BLOB); the
            # row is the same crease_pinch_factor Snake Hook remaps.
            pinch = float(values[PREFIX + 'snake_pinch']) ** 2
            extras.append(('pinch', pinch if self.settings.brush_type == 'CREASE' else -pinch))
        return extras

    def publish(self, payload, *, program=None, smooth_command=None, strength_override=None):
        from sculptcore.brush_properties import set_command_scalar, replace_command_stack
        common, extras, smooth_strength = payload
        if strength_override is not None:
            common = (strength_override, *common[1:])
        self._uniforms()
        for name, value in extras:
            if name not in self.by_name:
                # Toggle kernels do not consume the original brush's pinch field.
                if name == 'pinch' and self.settings.kernel_name not in ('PINCH', 'SNAKEHOOK', 'SHARP', 'CREASE'):
                    continue
                raise PropertyError("Kernel no longer declares " + name)
            uniform = self.by_name[name]
            if type(value) is not {0: float, 4: int, 10: bool}.get(uniform.scalar_type):
                raise PropertyError("Kernel scalar type changed: " + name)
        for index, value in enumerate(common):
            self.common.write(index, value)
        for name, value in extras:
            if name in self.by_name:
                self.access.write(self.by_name[name].index, value)
        for name, value in zip(('strength', 'radius', 'autosmooth', 'planeoff', 'spacing', 'invert'), common):
            setattr(self.brush, name, value)
        if program is not None and smooth_command is not None:
            set_command_scalar(self.manager, program, smooth_command, 'strength', 0, smooth_strength)
            key = program.ptr, smooth_command
            if key != self._command_stack_key:
                replace_command_stack(self.manager, program, smooth_command, 'strength', 0,
                                      native_layers(self.settings.snapshot(STRENGTH).stack))
                self._command_stack_key = key
            projection = self.settings.value('sculptcore.kernel.bsmooth.projection')
            set_command_scalar(self.manager, program, smooth_command, 'projection', 0, projection)
        self._last = payload

    def close(self):
        self.native.close()

    def view_image(self, sign=(1, 1, 1)):
        vector = self.brush.viewDir.vec
        for axis in range(3):
            vector[axis] = self.view_direction[axis] * sign[axis]
