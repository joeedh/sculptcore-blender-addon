# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Consumer-owned installation state; never put engine wrappers in the sample cache."""
from . import sampling


class StackUploads:
    def __init__(self):
        self.brush = None
        self.key = None
        self.generation = None
        self.uploads = 0

    def install(self, brush, access, stacks, *, command=None):
        """Each stack is atomically replaced; failed sets never publish a reuse memo."""
        stacks = tuple((index, tuple(layers)) for index, layers in stacks)
        token = getattr(access, 'token', None)
        if token is not None:
            from sculptcore.brush_properties import BrushPropertyError
            # A cached installation cannot authorize a retired manifest/owner.
            for index, _ in stacks:
                with access.executor.uniformSnapshotChecked(token, index) as snapshot:
                    if snapshot.status:
                        raise BrushPropertyError(snapshot.status)
        key = (sampling.epoch, command, token, stacks)
        generation = brush.configurationGeneration()
        if self.brush is brush and self.key == key and self.generation == generation:
            return False
        self.key = None
        for index, layers in stacks:
            access.replace_stack(index, layers)
            self.uploads += 1
        self.brush, self.key = brush, key
        self.generation = brush.configurationGeneration()
        return True
