# Generic brush custom-curve integration: current API findings

Inspected 2026-09-17 while completing persistent placement storage. These are
integration findings, not an approved implementation plan or a completed gate.

## Established API behavior

The fork's `doc/python_api/rst/info_owned_curve_mapping.rst` and the existing
`test_owned_curve_rna.py` exercise declarations directly on Brush/Scene as well
as nested PropertyGroups. Direct unset getters return None without allocating.
`curve_mapping_initialize(path)` stages pointer ancestors atomically, but requires
collection entries to exist. Native curve edits notify the actual owner and
preserve independent ID-copy ownership. The declared property is stored in the
system-property namespace, separate from the generic custom metadata root.

Consequently, integration does not inherently require adding a CollectionProperty
entry just to hold one curve. A stable per-property/device declaration on the ID
is a candidate worth reviewing against the originally proposed nested bank.
The existing direct-property tests are API evidence, not proof that a dynamic
registry of many declarations has acceptable startup cost or compatibility.

The generic stack schema currently stores generated descriptors only and reports
execution unavailable. Its stable property/device keys and dormant payload
preservation provide an association point for custom curves. Metadata-root swaps
already preserve separately declared curve runtime identity in real asset tests.

## Boundaries the next reviewed plan must resolve

- Declaration names, hash collision/identity validation, registration independent
  of the engine, missing definitions and saved orphaned curves.
- Direct declarations versus a nested bank: registration scale, non-destructive
  malformed-data inspection, lifetime and compatibility with unknown saved data.
- Creation and selection are distinct mutations. The scalar transaction cannot
  atomically create a system-property curve and change custom stack metadata.
  Specify failure/no-op behavior before exposing a combined authoring operation.
- An immutable custom reference must carry actual owner identity and the owned
  mapping's runtime key. Reads/writes must reject stale or cross-owner references;
  serialization must never store runtime pointer identities or sampled tables.
- Preset selection, disabling, reordering and stack clear must preserve dormant
  custom curves; explicit removal and reinitialization need clear stale-handle
  semantics. Native pressure curves remain authoritative in their own adapters.
- Verify real Brush and Scene copies, asset Save/Revert/fresh-process persistence,
  unregister/re-register, absent modules and generic Scene undo. Brush/native
  Scene authoring undo remains a separate open gate.

No new curve declarations, hidden node trees, fork edits or engine edits were
introduced by this investigation.
