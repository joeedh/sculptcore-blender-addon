# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Immutable effective settings shared by stroke, cursor and host scalar consumers."""
from dataclasses import dataclass
from types import MappingProxyType

from . import authoring, sampling
from .adapters import CAVITY, SIZE, SIZE_ALIASES, STRENGTH
from .evaluation import ScalarEvaluator, SPACING
from .legacy import ASSOCIATIONS
from .registry import PropertyError, finite
from .resolver import resolve
from .responses import PreparedResponse, SampleConfig
from .snapshots import capture

PREFIX = 'sculptcore.brush.'


def object_radius(context, size, position):
    """Project the effective diameter along the viewport's horizontal direction."""
    from mathutils import Vector
    from ..stroke import _pixel_to_world_length
    right = context.region_data.view_rotation @ Vector((1, 0, 0))
    inverse = context.active_object.matrix_world.inverted().to_3x3()
    world_radius = size.world * .5 * (inverse @ right).length
    if size.mode == 'SCENE':
        return world_radius
    projected = _pixel_to_world_length(context, position, size.pixels * .5)
    return projected or world_radius


def pixel_radius(context, size, position):
    if size.mode == 'VIEW':
        return size.pixels * .5
    from ..stroke import _pixel_to_world_length
    unit = _pixel_to_world_length(context, position, 1.0)
    return object_radius(context, size, position) / unit if unit else size.pixels * .5


def view_direction(context, position):
    """Object-space eye-to-surface direction for the actual dab center."""
    from mathutils import Vector
    inverse = context.active_object.matrix_world.inverted()
    view = context.region_data
    if view.is_perspective:
        eye = inverse @ view.view_matrix.inverted().translation
        direction = Vector(position) - eye
    else:
        direction = inverse.to_3x3() @ (view.view_rotation @ Vector((0, 0, -1)))
    return tuple(direction.normalized())


@dataclass(frozen=True)
class StrokeSettings:
    """Capture once; projection and device channels are explicit evaluation inputs."""
    properties: tuple
    brush_type: str
    kernel_name: str
    subtract: bool
    local_strength: float
    falloff: PreparedResponse
    cavity: PreparedResponse | None
    overlaps: tuple = (1.0,) * 100

    def __post_init__(self):
        evaluators = {item.definition.identifier: ScalarEvaluator(item) for item in self.properties}
        if len(evaluators) != len(self.properties):
            raise PropertyError("Duplicate stroke property")
        object.__setattr__(self, '_evaluators', MappingProxyType(evaluators))

    def snapshot(self, identifier):
        return self._evaluator(identifier).snapshot

    def _evaluator(self, identifier):
        try:
            return self._evaluators[identifier]
        except KeyError:
            raise PropertyError("Property is outside this stroke: " + identifier) from None

    def value(self, identifier, channels=(None, None, None, None), **kwargs):
        return self._evaluator(identifier).evaluate(channels, **kwargs)

    def engine_value(self, identifier, channels=(None, None, None, None), **kwargs):
        return self._evaluator(identifier).engine_value(channels, **kwargs)

    @property
    def size(self):
        return self.snapshot(SIZE).size

    def base_radius(self, projected_pixels, object_scale=1.0):
        """Projection receives the effective pixel radius; SCENE uses world diameter."""
        if not finite(object_scale) or object_scale <= 0:
            raise PropertyError("Object scale must be finite and positive")
        if self.size.mode == 'SCENE':
            return self.size.world / (2.0 * object_scale)
        radius = projected_pixels(self.size.pixels / 2.0)
        if radius is None or radius == 0:
            radius = self.size.world / (2.0 * object_scale)
        if not finite(radius) or radius < 0:
            raise PropertyError("Projection returned an invalid radius")
        return radius

    def radius(self, base_radius, channels):
        return self.engine_value(SIZE, channels, projected_radius=base_radius)

    def overlap(self, channels=(None, None, None, None)):
        """Preserve legacy compensation independently of falloff LUT interpolation."""
        from .. import mapping
        spacing = self.value(SPACING, channels)
        if (not self.value(PREFIX + 'spacing_attenuation') or spacing >= 100
                or self.brush_type in mapping.TANGENT_DRAG
                or mapping.KERNEL_BY_TYPE.get(self.brush_type) in ('GRAB', 'KELVINLET', 'SNAKEHOOK')):
            return 1.0
        return self.overlaps[spacing]


def capture_stroke(brush, scene, *, kernel_name=None):
    """Resolve owners and sample curves without writing persistent authoring data."""
    from .. import mapping
    kernel_name = kernel_name or mapping.KERNEL_BY_TYPE.get(brush.sculpt_brush_type)
    if kernel_name is None:
        raise PropertyError("Brush has no supported SculptCore kernel")
    local, parent = authoring.store(brush), authoring.store(scene)
    identifiers = tuple(definition.identifier for definition in authoring.registry.definitions()
                        if definition.identifier not in SIZE_ALIASES
                        and (definition.identifier not in ASSOCIATIONS
                             or ASSOCIATIONS[definition.identifier][0] in (kernel_name, 'BSMOOTH')))
    properties = capture(authoring.registry, identifiers, local, parent)
    values = {item.definition.identifier: item.value for item in properties}
    falloff = sampling.falloff_response(brush, values[PREFIX + 'hardness'])
    cavity = None
    if (values[CAVITY + '.use_automasking_custom_cavity_curve']
            and (values[CAVITY + '.use_automasking_cavity']
                 or values[CAVITY + '.use_automasking_cavity_inverted'])):
        resolved = resolve(authoring.registry, CAVITY + '.cavity_factor', local, parent)
        owner = resolved.value_owner.owner
        path = ('mesh_automasking_settings.cavity_curve' if resolved.value_owner.kind == 'BRUSH'
                else 'tool_settings.sculpt.mesh_automasking_settings.cavity_curve')
        cavity = sampling.native_response(owner, path, SampleConfig(clamp_output=True))
    return StrokeSettings(properties, brush.sculpt_brush_type, kernel_name,
                          brush.direction == 'SUBTRACT', float(brush.strength), falloff, cavity,
                          sampling.overlap_table(brush))
