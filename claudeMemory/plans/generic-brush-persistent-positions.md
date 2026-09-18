# Plan 4 saved plural positions

Status: implemented and bounded completion gate passed, 2026-09-17. Fresh
`review_positions_storage` and `review_positions_semantics` plan reviews and
implementation audits are folded in. See
[completion evidence](../codebase/generic-brush-plan4-evidence.md#saved-plural-positions--2026-09-17).

Persist placement independently on each Brush/Scene property record, including
native-backed definitions. Positions never follow effective value/stack owners.
Expose store read_positions(definition), write_positions(definition, positions),
reset_positions(definition). No product UI or sorting renderer is enabled here.

Absent placement override returns immutable definition.positions without writes;
explicit empty override hides all placements. Reset returns to definition defaults.
Keep overrides explicit even if equal to today's defaults so future definition
changes do not reinterpret authored placement. No engine imports/dependency.

Use existing atomic scalar transactions. Record positions_version=1 and
positions_order as a JSON array of stable keys (empty array means explicit empty).
Each entry in positions group is keyed by SHA256 of the location string, with
full location and signed-int32 sort_index stored/checked. Preserve unknown sibling
fields and dormant entries on reorder/removal. Bound lists to 128 entries and
locations to 1024 UTF-8 bytes without NUL; accept unknown location identifiers.
At most one position per location; strengthen Position/Definition validation to
match this logical placement rule (currently only exact pairs are deduplicated).
Share pure validation between definitions and saved data. Input is immutable
Position tuple; every call validates it before writes. Preserve input order;
the eventual renderer sorts using sort_index and a deterministic tie-break.

Storage review corrections: reuse `record_key(location)`'s 54-byte base32 digest,
not a 64-byte hexadecimal key (Blender allows 63 bytes). `positions_order` is an
exact JSON string scalar, never an array. Bound it to 16384 characters before
parsing; reject malformed JSON/shape/duplicates and excessive nesting cleanly.
Reset checks owner write eligibility even for no-ops and returns before publication
when both header leaves are absent, so untouched reset creates no root/record.
Only one header leaf present is malformed on read; whole write repairs a missing
leaf unless the present version is unsupported/mistyped. Reset can remove ordinary
scalar partial headers. Incoming same-key entries must already have the exact full
location identity (missing/mistyped identity also rejects); unrelated dormant
entries remain uninterpreted. Native whole-root depth/type/node limits still apply.
Placement never checks native stack/value availability. A new Registry/default
revision test must distinguish explicit equal-default overrides from reset defaults.

Header validation is placement-local: scalar/stack/policy reads and writes
preserve unknown placement schemas. Placement access rejects future/mistyped
versions, malformed order/active records or location-key mismatch without change.
Whole replacement repairs ordinary scalar/order fields and absent version;
future/mistyped version, non-scalar ancestors/leaves and static-type mismatches
remain rejected. Existing same-key full location mismatch rejects as a collision,
not an invitation to overwrite. Unknown dormant records are not interpreted.

Reset atomically DELETEs version and order, retaining keyed payloads opaquely.
Absence is determined by missing version/order (dormant positions alone allowed).
Reset rejects future/mistyped versions and malformed top-level positions group;
it can remove malformed scalar order. Native transaction protects non-scalar
order/version. Empty write to absent record must create an explicit override.

Gates: pure import/validation; real Blender default/empty/reset, native properties,
owner isolation with both inheritance flags, unknown/dormant preservation,
collision/rejection/rollback, malformed/future version, independent copies,
save/read without authoring modules, external asset dirty/no-op/Save/Revert,
headed Scene undo/redo, stack/scalar regressions and restaged package smoke.

Next: inspect custom-curve bank integration against the declared owned-curve API.
