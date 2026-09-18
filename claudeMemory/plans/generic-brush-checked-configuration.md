# Plan 3: checked scalar and device-stack configuration

Status: complete, 2026-09-16. Fresh reviews are complete and typed extra emission
passed its prerequisite gate. Final native configuration, staged uploads and
query bindings pass 16 native suites and the actual typed/common Python binding
test. The addon-only rebuild, restored regressions, declarations and TypeScript
checking also pass. [Evidence](../codebase/generic-brush-plan3-evidence.md#checked-configuration-and-binding-gate).
This applies the reviewed typed-integration requirements at the Brush and
manifest-index binding boundaries. Full prepared execution and input acquisition
remain later gates.

## Native configuration

1. Resolve local FLOAT32/INT32/BOOL properties with exact requested type and
   retained declaration validation. Value writes use the existing checked
   scalar transport. Stack writes additionally require dynamic eligibility and
   writable local ownership. Inherited-only targets reject; configuration must
   not silently modify a parent's stack. Common native properties use explicit
   member eligibility when no generated declaration exists.
2. Add checked ordered stack replacement using primitive vectors for device
   types, modes, factors, enabled flags, table offsets and flat float samples.
   Validate matching lengths, maximum four supported unique devices, flags 0/1,
   finite factors/samples, supported mixes and offset coverage before changing
   state. Tables have zero (identity) or 2..65536 samples. Commit the complete
   candidate once. Copying must clear transient input caches.
3. Add checked upsert/configure, enable, move, clear and bulk-table replacement.
   Updating an existing device preserves its position, table and enabled flag.
   New devices append. Move addresses the unique device and destination index;
   invalid commands preserve the whole stack. All mutators return explicit
   errors and increment configuration generation only after a successful change.
4. Existing float/common/name entry points delegate to checked operations while
   preserving signatures. Sequential sample uploads validate before allocation.
   A resized table is staged with deterministic contents and per-sample presence;
   publish only after every index is supplied. Pending imports fail evaluation
   and preflight rather than silently using an incomplete curve. Existing valid
   tables remain intact until publication; bulk replacement/clear discard pending
   imports. Invalid indices/counts/nonfinite values do not mutate either table.

## Bindings

5. Expose exact numeric transport as explicit scalar type plus double. Use
   manifest-index wrappers on CommandExecutor, plus wrappers for the existing
   common property IDs. Query generation identifies the current name/index
   mapping and changes on every query, including failed queries. Checked calls
   require the expected generation so stale indices reject. Return errors
   explicitly; read/evaluate results carry status and double value.
6. Reflect primitive-vector methods and result descriptors; regenerate Python
   and TypeScript declarations through existing tooling against the rebuilt
   DLL. Preserve legacy methods and litestl ABI implementation. Run actual Python
   binding tests with exact large integers, bool transport, stack preservation,
   ordered mixes, failed atomic writes, bulk tables and stale query generations.
   Do not vendor until those tests pass against the exact built DLL.

## Gate and limits

Fresh adversarial reviews of native configuration/compatibility and binding
transport/lifetime before implementation. Run native checked-configuration and
existing typed/registration/storage tests, then the actual Python binding gate.
Record commands, binaries and generated artifacts.

The typed extras compiler gate supplies tests/assets/typed_extras/typed_probe.sbrush.
Build the native DLL with that fixture directory explicitly enabled for binding
acceptance; native configuration unit tests may also declare typed props directly.
This gate does not make raw native fields automatically dynamic,
deliver tablet events, or complete per-command independent configuration.

## Folded native and binding review corrections

- Land typed extra emission before claiming typed binding acceptance. Use real
  FLOAT32/INT32/BOOL extra kernels instead of a test-only reflected registry.
  This refines Plan 3's internal order without changing the eight-plan dependency
  graph. The named-storage gate remains useful independently.
- Supported devices are PRESSURE through SPEED; modes are MULTIPLY, ADD,
  SUBTRACT, DIFFERENCE, LINEAR; factors are finite in [0,1]. Validate native flag
  bits and shared table limits. Offsets have count+1 entries, start at zero,
  end at sample count and are monotonic/bounded. Clear/full replacement repair
  corrupt old state; failed replacements preserve even corrupt state.
- Resized sequential imports have evaluator-visible pending state. Copy pending
  configuration and presence while clearing transient input samples. Same-size
  calls edit one sample atomically when no import is pending; repeated pending
  indices replace that sample without advancing completion count. Count changes
  start a new pending import. Configure/enable/move preserve pending state;
  clear/bulk replace cancel it. Invalid input leaves prior progress unchanged.
  Disabled pending layers still reject checked evaluation. Generation advances
  at the first accepted pending sample and on later accepted state changes.
- Scope this gate to checked evaluation rejection of pending imports. Current
  legacy mesh/grid preparation can still substitute lookup defaults; complete
  early entry-point rejection remains the prepared-execution gate. Do not claim
  incomplete-import geometry safety from configuration tests.
- Checked custom dynamics require an actual retained eligible declaration.
  Undeclared custom scalars reject; only explicit common properties fall back to
  native eligibility. Include invert via a common ID and pass its input context
  to loadCommonProps. Legacy FLOAT64 configuration becomes a diagnosed unsupported
  operation. Duplicate add becomes upsert, preserving existing settings/order.
  Corruption tests must inject invalid native state directly, and separately
  verify the checked setter rejects it.
- Configuration generation covers these checked APIs, including legacy delegates;
  it does not cover raw props/dynamics vectors/native-field writes. Full prepared
  execution cannot assume it detects such writes. Keep query identity separate.
- Tokens are positive int32 values unique across all executor queries within a
  process, never reused. Exhaustion refuses further queries instead of wrapping.
  Invalidate before each query attempt. Capture Brush and StructDef identity and
  reject replacement after query, including same-kernel queries on another brush.
- Keep a private canonical query mapping. Existing borrowed manifest pointers
  are mutable and invalidated by requery; document that legacy lifetime. Add an
  owned by-value snapshot accessor. Checked calls never trust caller-writable
  manifest fields. Scalar results likewise return owned {int status; double value}.
- Reflected selectors/statuses use plain ints, not enum arguments: TypeScript's
  current marshal path lacks enum argument support. Keep native enum types behind
  validated int wrappers. The native API uses const primitive-vector references.
  Reflected wrappers use non-const references because the current Binder tries
  to instantiate vector resize methods for const vectors. The wrappers only
  read the arrays, and actual binding tests assert their contents stay unchanged.
  Python adapters reject unintended types and oversized fixed-width selectors
  before marshalling; native double-value tests separately prove C++ rejection.
- Generate Python/TS declarations against one explicit absolute DLL in fresh
  processes, assert the loaded path, and record its hash. TypeScript generation
  uses LSTL_GenerateTypescript and its length-prefixed blob. Do not equate generated
  TS declarations with a runtime transport pass.

Required additional cases: partial resize with prior table, same-size sample
edits, repeated indices/count changes, invalid input after progress, pending copy
and disabled state, corrupt-stack repair, rejected-operation generation stability,
replacement brush/wrong executor tokens, same/different/failed requery, owned
snapshot lifetime, wrong/read-only/inherited/static/undeclared targets.

## Implementation notes

- The Python adapter is engine/python/sculptcore/brush_properties.py. It exposes
  CommonProperties and UniformProperties with shared validation, immutable
  metadata snapshots and strict Python types/int32 selectors before calling
  native methods. Keep the executor and Brush alive for the view.
- Query tokens are distinct from configuration generations. Every query attempt
  consumes a fresh token. Native reads return owned results; borrowed metadata
  does not route either the checked or legacy indexed setters.
- Configuration generations count accepted scalar writes and changes to device
  configuration, including pending upload progress. An identical stack update
  is a no-op. These counters do not cover raw fields, raw property edits or
  direct named working-store writes, so preparation must still validate them.
- Reflection ABI stays at 1: the dispatcher/descriptor protocol is unchanged;
  reflected object sizes and member offsets are discovered from the loaded DLL.
  Python and TypeScript declarations are regenerated from that exact library.
  TypeScript declaration generation alone is not a runtime transport test.
- The initial binding build failed on unqualified Vector names and the const
  vector reflection limitation. The first Python run failed only its final
  common-invert assertion: the test reused a fixture that declares invert
  static. That static rejection is intentional; the common-eligibility case
  now uses a fresh Brush. Logs retain both failures and their passing reruns.
