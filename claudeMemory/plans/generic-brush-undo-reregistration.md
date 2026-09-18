# Plan 4 gate repair: addon re-registration after undo

Reviewed correction, 2026-09-17. Actual headed native undo works with
the addon disabled, but re-enabling the addon fails ObjectModeType subclass
validation. Before disable, the registered SculptCoreMode's Python base and
the current bpy.types.ObjectModeType already have different identities after
undo/redo. Background unregister/register without a public base lookup passes.

Both fresh reviewers reproduced the failure without undo: registering a mode
clears the parent StructRNA Python cache in bpy_rna.cc; the next public lookup
recreates ObjectModeType, so the original class fails subclass validation.
ObjectModeType lacks the permanent _bpy_types.py wrapper already provided for
RenderEngine, AssetShelf and FileHandler. Both runtime controls proved that
anchoring the base fixes identity and repeated registration.

Accepted implementation: add the empty ObjectModeType(_StructRNA,
metaclass=_RNAMeta) wrapper beside RenderEngine. Stage scripts and use fresh
processes; no native rebuild, class reconstruction or validation weakening.
Add background tests with explicit public lookups, two independent subclasses
and repeated cycles. Retain headed disable/undo/enable plus payload checks,
actual custom mode enter/exit and pending undo-key lifetime coverage.

Original candidate (superseded by the proven correction above): investigate
the fork's RNA/Python type lifetime and memfile undo path. Preserve
the registered base class's authority across undo; do not weaken subclass
validation or globally skip failed addon registration. Prefer a bounded native
correction if a wrong type-cache invalidation/refinement is proven. If Blender
intentionally replaces the base Python type, reconstruct the addon mode class
against its current base only while unregistered, preserving callbacks and
registered class identity for the lifetime of each registration.

Gate: existing collection/native authoring undo and background DLL-independent
registration tests pass, followed by full addon disable, undo while disabled,
and real re-enable. Check ordinary custom mode enter/exit and pending custom undo
state lifetime. Preserve unrelated RNA and sculpt behavior. Fold both fresh
reviews and the proven root cause into this plan before implementing the fix.
