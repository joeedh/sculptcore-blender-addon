# Debugging notes

## Brush spatial support (2026-09-18)

* Test region selection separately from displacement. A nonzero custom endpoint
  exposed both whole-mesh selection and clamped-distance spill; matching an
  all-node reference would preserve both bugs. Use independent geometry and
  queried-leaf counts. Keep previously reached grab leaves when radius grows or
  symmetry changes, since their live bounds may have moved away from the anchor.
* Native `dumpVertCo` returns four floats per mesh vertex; multires position
  output returns three. Geometry assertions must account for the different strides.

## Owned-curve headed/API follow-up (2026-09-16)

* Space synthetic mouse move, press and release across event-loop turns. Sending
  every event in one debug request can leave the next assertion ahead of button
  processing. Screenshot immediately after an action when diagnosing a no-op;
  API state after Apply alone cannot distinguish a missed click from a rejection.
* The dialog initially focuses Min X text. A first click can finish text editing
  rather than activate another control. Selected-point rows change popup height
  while its bottom remains anchored; derive new coordinates from a screenshot.
* A new Blender window can contain only a View3D and use different dimensions
  from the original. The tested second window was 1216x720, not 1280x800. Use its
  own sidebar coordinates and event target; a successful request alone does not
  prove a popup was opened. The stale concurrent Apply screenshot shows the
  expected explicit revision error.
* Headed asset activation is asynchronous. Save As can finish before the asset
  library is ready to activate; let the event loop run before retrying a known
  cancelled activation. Never retry a transport-timeout mutation blindly.
* Direct ID declarations live in system properties; ID bracket lookup accesses
  user properties. Use a nested PropertyGroup for intentional raw-definition
  fixtures. Registered annotation properties are removed using RemoveProperty;
  their Python class need not appear as an attribute of bpy.types.
* Link a loaded library Object into a scene before testing override_create.
  Merely loading an unused indirect ID returned None; linking made it a directly
  referenced overridable ID. The owned-curve override policy test then passed.
* Full API documentation generation writes bmesh.ops.rst in the fork even when
  output points elsewhere. For this bounded API gate, separate `--partial=bpy.*`
  and `--partial=info` runs generated methods, metadata and the guide without
  unrelated source-tree output. RST generation is not an HTML/Sphinx build claim.
* Array-watch safety hooks must distinguish membership changes from relocation.
  Walking every child on each SetIndex/append made 32767-point construction
  quadratic while an unrelated live editor watch existed. Exact-array watch
  invalidation plus replaced-subtree free hooks suffices for SetIndex; only
  actual relocation needs all descendant watches invalidated. RNA removal and
  override clear perform memmove before resize and therefore need their own
  pre-move hook. See the reviewed performance plan for all branches/tests.

## Owned CurveMapping implementation (2026-09-15)

* A const CurveMapping still exposes writable point arrays. Keep snapshots
  opaque and expose explicit deep copies for edits; only snapshots cross threads.
* Invalidate detach/reparent operations, not just frees. Remove/reinsert can
  otherwise resurrect a record before any attachment check observes removal.
* Registry erasure can destroy canonical IDProperties and reenter lifecycle
  hooks. Retain removed records until map mutations finish and the lock is
  released; disable hooks before static registry teardown. Use keyed free
  lookup and a single subtree walk, avoiding records-times-properties overhead.
* Native curve evaluation converted the float table index to int before
  checking bounds. Huge finite queries can overflow that index; range-check
  first and reject non-finite owned inputs/results. Native sampled endpoints
  may differ from authored coordinates by a few float ULPs.
* IDP_NewString's StringRef overload still performs string copying. For an
  embedded-NUL byte-string test, allocate the full buffer first, then write
  its actual bytes and subtype; otherwise the intended differing byte is lost.

* Test both ordinary custom properties and the actual dynamic-RNA system
  property root when proving old-reader preservation. Passing a tagged group
  through `owner["key"]` alone does not exercise registered PropertyGroups.
* Finite control points do not guarantee finite native curve tables. Coincident
  vector endpoints and extreme float coordinates can create NaN/overflow in
  native evaluation. Validate the materialized table/range/extrapolation too.
* `IDP_SetIndexArray` transfers contents; free only the source shell afterward.
  `IDP_CopyPropertyContent` swaps contents before freeing a temporary, so
  lifetime registries need destination invalidation as well as free hooks.
* RNA function results can reconstruct discrete pointers, and collection
  foreach/raw-array access bypasses field setters. Retained point/iterator
  safety needs explicit handling of these paths and mathutils callbacks.
* A retained CurveMapping does not retain addresses inside a replaced point
  array. Curve numeric buttons store such addresses; owned editing needs stable
  staging values and an edit session that survives active-button redraw transfer.
* Native brush dirty tagging only affects linked assets. Use real editable
  external assets for notification tests, with different active and edited
  brushes. Local `bpy.data.brushes.new()` is not a dirty-state oracle.
* Native CurveMapping field dirty notifications are distinct from recomputing
  its evaluator. Scripts still call `CurveMapping.update()` after point edits.
* Enabling Blender GTests can rebuild most libraries even for one focused test.
  Record and restore the existing WITH_GTESTS/WITH_TESTS_SINGLE_BINARY options.
  This fork's iterator use needs BLI_listbase.hh, and an explicit C-array Span
  needs its length; neither was supplied transitively in the codec's first build.
* Windows imported-configuration mappings need an empty final entry to allow
  generic IMPORTED_LOCATION tools such as Git::Git. The isolated reproduction
  fails without that entry and succeeds with it; full configuration then works.
* Removing a stale clang-cl .pch alone is insufficient with this Ninja setup:
  the declared output is cmake_pch.cxx.obj. Remove that owning generated object
  and force SCCACHE_RECACHE=1 to avoid restoring a PCH made with an earlier
  MSVC patch version. Do not change source to work around a stale build artifact.

## Generic brush migration baseline (2026-09-15)

### Owned RNA integration

* `FUNC_SELF_AS_RNA` passes a full PointerRNA value before context/reports.
  Function return `PARM_RNAPTR | PROP_THICK_WRAP` preserves owned handles.
  Custom collection getters must return PointerRNA; makesrna only auto-wraps
  its three specially recognized native iterator getter names.
* Python numeric conversion can call user code via `__float__`, `__index__`,
  or sequence iteration. It can delete the RNA owner. Revalidate after every
  conversion before setters, function dispatch, or error formatting.
* Generic RNA access guards do not protect direct generated native accessors.
  Manual field/iterator accessors are required at those boundaries too.
* Dynamic system-property roots also exist on Bone and related substructures.
  An owned ID-rooted property cannot attach there and wait for BKE acquisition
  to reject it: validate the entire declaring ancestry before attachment.
* A callback can unregister its own declaration or delete its owner. Retain its
  Python callable, tag the actual owner before Python runs, and make no accesses
  through saved owner/property pointers afterward. A native setter's pending
  callback must survive refreshing reads between setter and update.
* Avoid rerunning an earlier source-insertion script after later scripts have
  modified its inserted block: exact whole-block matching can insert duplicates.
  Use stable function/section replacements and compile the resulting sources.
* In this build, retaining both `libraries.load` context objects in the large
  dynamic-RNA harness retained its wrapper namespace at shutdown. Prefix probes
  were clean through save/write, then reported retained allocations after link.
  Deleting the context objects removed the report; deleting only retained curve
  functions did not. Release those test context dictionaries explicitly. Native
  read/edit/function/iterator lifetime probes were clean independently.

* Blender 5.3 has per-brush `use_unified_*` flags, but the shipping addon still
  reads deprecated Scene UnifiedPaintSettings flags. Freeze both and decide
  compatibility explicitly; native UI and current execution already disagree.
* Native size setters rescale the paired pixel/world diameter. Modal cancel
  cannot restore just one scalar without rounding damage to the other.
* Background Save As/Save invalidates the asset list. Reactivate the scratch
  asset before dependent Save/Revert: asset_activate explicitly performs a
  blocking fetch in background mode. Immediate Save/Revert can fail polling
  with "Asset loading is unfinished", even though the asset file exists.
* Run plane-family baselines on geometry within the authored plane-side
  support and assert actual displacement. Positive planeSide ignored the first
  concave fixture; the convex fixture exercises CLAY/FILL and reproduces exactly.
* Capture process status before printing a log tail in PowerShell; otherwise
  Get-Content success can hide Blender's nonzero exit. Also require explicit
  success markers and scan headed stderr for callback exceptions.

## Remote Blender Python (2026-09-15)

See [the debug server guide](codebase/blender-debug-server.md) for the opt-in
server, launch commands and tested limits.

* The native SculptCore remesh pipe debugger cannot inspect Blender RNA.
  An older Blender fork commit (`47df4abf422697b1f8dfb38f8cfc917f52c3da55`)
  also contained a Python REPL, but it is absent from the current checkout.
* Use Blender's main-thread timer for remote Python. Background script loops
  require explicit pumping; a listener thread alone cannot service `bpy` work.
* Hook `load_pre`, not just `load_post`: unsuccessful loads can stop timers too.
  Test both a malformed existing `.blend` and a successful save/reopen.
* `read_factory_settings` can reset addon registration. The first integration
  harness called unregister again afterward and hit missing `bl_rna` metadata.
  Use a scratch save/reopen for file-load lifecycle tests and `addon_utils.disable`
  for an intentional addon teardown.
* The protocol suite and both real Blender modes passed. Headed tests need
  explicit success markers because an exception in an app timer does not
  necessarily give Blender a nonzero exit status.

## Owned editor path watches and native test startup

- Empty collection items can have identical bytes. An unset UI target needs
  structural watch tokens, not pointer/content equality. When an IDProperty
  array reallocates or moves, expire descendant watches too: otherwise their
  registry keys point at freed inline storage and can collide with worker-side
  temporary allocations. Existing curve definition records remain independent.
- Capture an owner token even when its system-property root is absent. Root
  pointer equality alone cannot detect an owner-content swap between two empty
  states.
- Standalone Windows native test executables need both `bin/blender.shared`
  and `bin` on PATH, plus the test-assets/test-release arguments used by CTest.
  Missing DLL search paths can leave a process waiting before emitting any
  GTest output. Stop only the verified test-owned process and relaunch with the
  CTest runtime environment; an empty log is not a failed assertion or a pass.

## 2026-09-16: owned editor gate and typed engine build

- Removing a selected curve point hides its numeric/handle rows. The popup keeps
  its top position, so Apply moves upward by 62 pixels. The working screenshot
  proves removal; clicking the old Apply location cancels outside the popup.
  Use the resulting layout in the test driver and assert the commit callback.
- Node reported a missing yargs index.js even though its package existed. The
  sandbox could list the pnpm hardlinks but could not read package.json. Running
  the authorized build dispatcher with dependency/cache access resolved it;
  no dependency reinstall or package change was needed.
- Source-first dynamics adds float-to-integral destination conversions after
  evaluation. Finite source values can exceed destination bounds. Guard before
  casting and retain the caller default on failure.
- A multilayer test must distinguish conversion timing: 3*.5+.4 yields 2 even
  with premature rounding; 3*.5+.6 yields 2 only when conversion is deferred.

- New checked property reads cannot derive the owner of an inherited bound or
  getter-backed property from StructDef. Reusing Property.owner can select a
  stale instance; assigning the child owner reads a different object's fields.
  Reject these cases explicitly until the resolved representation carries the
  declaring owner. Keep unbound defaults and legacy APIs separate.
- Shader reserved-name checks must cover fields that C++ stores do not name:
  nonaccum and grab_dab_gen are fixed BrushUniforms fields. Missing either lets
  an extra compile on the C++ side and later emit duplicate WGSL members.
- Python helper scripts must use explicit UTF-8 when editing repository docs.
  Windows default decoding can preserve old bytes yet emit new punctuation as
  cp1252; decoding raw bytes then write_text also duplicates CRLF unless newline
  handling is explicit. The gate docs were normalized and verified as UTF-8.

## 2026-09-16: standalone native test DLL popups

- The user reported multiple missing-DLL dialogs during native test launches.
  Direct diagnosis reproduced `0xc0000135` for both standalone Blender GTests
  without the runtime PATH; required DLLs were present in `bin/blender.shared`
  and `bin`. All eight engine suites ran directly with status zero. The exact
  DLL names in the user's dialogs were not captured.
- Use `scripts/run_blender_native_tests.py` for standalone Blender GTests. It
  prepends those runtime directories only in the child environment, uses bin as
  cwd and CTest's asset/release arguments, and suppresses inherited Windows
  loader/error dialogs. It preserves/restores the launcher's process error mode.
  No global PATH or installed DLL changes are needed.
- Require exact completed and passed test counts, not just exit zero or a pass
  substring. GTest can report zero tests successfully. The launcher clears
  inherited GTEST_* selection/sharding controls and retains full NTSTATUS,
  binary hash and stdout/stderr, including failure and partial timeout output.
- Verified real 14 runtime + 6 codec passes in `tests/native-launcher-verified/`.
  Nine negative cases, including a real suppressed missing-DLL launch, passed in
  `tests/native-launcher-negative/`. Earlier 14/6 success logs were real later
  configured runs; the initial loader failures should have been reported too.

## 2026-09-16: typed declaration registration

- StructDef numeric factories default to binding offset zero. New generic stored
  properties must pass -1 explicitly, or a non-null owner redirects them into
  the first owner field. Metadata adoption must not invoke getters or setters.
- Keep accepted declarations separate from mutable values and compare original
  default/range presence and doubles. Two different integer intervals can have
  identical representable bounds but still be incompatible declarations.
- A double decimal endpoint can round to a different FLOAT32 value. Derive
  representable bounds and validate the converted value; otherwise writing 0.1
  to a float minimum rounded from 0.1 may fail incorrectly.
- An absent default is not an authored zero. Range validation must check
  hasDefault before testing a manifest default against its range.
- createExtraBrush initializes working slots. Collect registration manifests
  using scratch Brushes so a later conflict does not mutate live slots.
- litestl math Vec has pointer conversion and no value operator==. The initial
  new mesh/grid no-mutation assertions compared addresses, not coordinates.
  Use component comparisons or memcmp of the three float components for exact
  geometry checks; do not change the unrelated litestl submodule for this.
## Stroke failure propagation

A native negative moved-count must reach the modal operator. Dyntopo wrappers
must return it, scalar/symmetry dispatch must stop, and preview rejection must
call the existing rollback finish path at both invoke and modal boundaries.
Checking only native geometry or batch return codes misses dropped scalar
results. The boundary regression script compiles actual stroke function bodies
with fake native calls; headed modal acceptance remains a separate gate.

## Named storage integration

- Record `--kernels-extra ../brushes` explicitly in addon engine gates. A passing
  test compiled without SCULPTCORE_EXTRA_BRUSHES does not prove its conditional
  extra-kernel assertions ran. Check a positive extra-branch marker as well as
  the test exit code.
- engine/tests/test_util.h defines test_end as a function. `test_end;` does
  nothing; use `return test_end()` to propagate assertions and the leak check.
- Generated identifiers serve assignment targets too. Replacing writable vector
  indexing with a read-only store requires evaluated setter emission for simple
  and compound assignments, including custom context fields in host stages.

## Typed extra compiler gates

- Registry and C++ emission must share field semantic validation. Registry-only
  scalar metadata checks miss duplicate names, field kinds and native members.
- Registry factory calls must use the same normalized name as C++ definitions.
  A mixed-case brush attribute/class pair exposed a mismatch invisible to NUDGE.
- Extra-dir builds generate C++ only. Emit fixture shaders explicitly and run
  Tint plus spirv-val. Require a vertex body that actually reads the new fields;
  a host-only kernel can emit a valid empty shader. WGSL reserves `active`, so
  use a portable local name such as `do_apply` in shared DSL fixtures.
- Grid standalone applyDab currently loads only common props. Typed property
  consumer tests use applyProgram; this does not close standalone preparation.
- GridBrushExecutor requires a valid domain at construction. Allocate the grid
  executor only for the grid branch of a mesh/grid test.

## Checked brush configuration bindings

- Reflected const Vector references instantiate Binder<const Vector<T>>, which
  tries to bind mutating resize methods and fails compilation. Use ordinary
  references at the reflected wrapper and const references in the implementation;
  test that caller arrays remain unchanged. Preserve the litestl ABI.
- Brush headers also compile in standalone sbrushc. Qualify util::Vector rather
  than depending on an executor's using-directive to make the name visible.
- An actual retained @static declaration takes precedence over common-property
  fallback eligibility. A common-invert test must use a fresh Brush or a kernel
  whose invert declaration explicitly supports dynamics.
- Owned manifest/result snapshots and private query mappings avoid using mutable
  borrowed descriptor fields to route writes. Requery invalidates tokens even
  when querying the same kernel or when the new query fails.

## Prepared execution prerequisites

- Checked property evaluation previously reset/repopulated live device input
  caches. Use the explicit const-context Dynamics overload during preparation;
  copying Dynamics would allocate tables. Reverse input scanning preserves the
  existing last-input-wins policy, including a final nonfinite sample.
- This does not make the whole property accessor read-only: owner assignment and
  custom getters still need a deliberate preparation policy.
- Static registered properties are unbound metadata/value storage, while static
  generated kernels read native members or typed slots. Prepared execution needs
  the authoritative static accessor bridge; reading the unbound default is not
  validation of the value the kernel will use.
- Do not copy Brush/StructDef for transaction isolation. Their self-pointer and
  owned property pointers require explicit candidates/snapshots. Keep generated
  extra registry lookup behind brush.cc to avoid a sbrushc/brush build cycle.
- Keep the native descriptor roster in a fixed table exposed through std::span.
  A function-static util::Vector survives until process teardown, so test_end()
  reports its allocation even when the value/geometry assertions all passed.
- Common properties remain authored sources even for a static kernel declaration:
  loadCommonProps still fills their native caches. Other static uniforms read and
  write native members or typed slots. Do not use planeSide for integer tests;
  its native type is float. activeGroup is a native integer.
- validateScalarDeclarations checks compatibility without retaining metadata or
  creating properties. registerScalars repeats it before publication because raw
  edits can invalidate an earlier successful check. It does not validate authored
  values or device stacks; those belong to prepared scalar evaluation.
- Property::name is public and can diverge from its StructDef key. Authorize a
  configured stack using canonical lookup identity, not name/type alone; otherwise
  a renamed stray property can impersonate a prepared common property.
- Generated factories append uniform manifests. Start each scratch command with
  an empty definition; reusing it across kernels leaves duplicates. Candidate
  manifests must come from scratch factories, not mutable reflected snapshots.
- litestl::Vector has no const data() overload. Expose const element-backed spans
  with an empty guard instead of changing the shared litestl submodule for this.

## Prepared mesh execution boundaries

- A spherical distance metric does not guarantee zero falloff outside radius:
  Gaussian is nonzero at t=0 and a custom LUT may be too. The first resolved path
  accepts Smoothstep/Linear only. Radius zero is a no-op; reject positive radius
  when its reciprocal overflows before publishing caches.
- Generated host stages can change radius or surfacePos after node selection;
  host-free vertex/reduce code can also assign native or extra uniforms. A
  conservative generated capability must exclude shared-state writes before
  admitting a command to immutable prepared execution.
- Vertex bundles expose executor/context references. Checking only an assignment's
  root identifier would allow nested context access in emitted IR; whitelist direct
  geometry members. The actual parser already rejects `.ctx` as a reserved token,
  so test parser rejection separately from the emitter's general nested-chain guard.
  Neighbor normals are live references, so neighbor writes are also ineligible.
  Unknown free calls may accept references; numeric constructors/casts need an
  explicit exception because they share the emitter's fallback call branch.
- SpatialTree::filterNodes uses cached bounds and increments hit-node diagnostics.
  Validate before filtering; updateQueries after accepted geometry changes so the
  next dab can find translated vertices. Use getRoot(), since root is private.
- A radius regression needs multiple leaves and a moved vertex owned by a leaf
  excluded at the raw radius. A one-leaf mesh cannot detect incorrect selection.
- Extras extend the reflected enum, not the compiled SculptBrushes C++ constants.
  Discover fixture IDs by exact Binder enum names when several fixtures share
  identical uniform declarations; do not select the first typed_count manifest.

## Prepared grid execution boundaries

- Multires domain pointers can reuse an allocation after invalidation. Cache the
  live Multires owner and its domainGeneration at attachment, and check generation
  before dereferencing the cached domain or tree. Executor-owned endStep retains
  its level while dropping finer domains, so rebaseline that successful fold.
  External invalidation requires reattachment; the Multires owner must stay alive.
- A matching GridStrokeLog domain does not prove its capture transaction is still
  open. Bind its pointer and open-step serial at beginStep. Attach or close/reopen
  must invalidate the binding even when the log and domain addresses are unchanged.
- preparedScalarSafe guarantees no shared scalar writes, not compact geometric
  support. An extra kernel may translate every vertex in a selected leaf, including
  seam vertices outside the query sphere. Refresh bounds for all occurrence leaves
  of moved vertices. Undo/redo need the same closure; refreshing captured owner
  leaves alone leaves incident nonowner bounds stale. Test a partial-region query,
  not just whole-domain translation.
- Successful zero/empty dabs clear last-dab result sets but retain stroke touched
  sets and pending normals. Failed dabs preserve both. Compare deferred normal
  refresh and post-undo normals against full-domain recomputation.

## Prepared program execution boundaries

- Program overrides are typed base-value overlays applied before dynamics.
  Temporary working values must restore initialized flags and store lengths as
  well as scalar values. Snapshot existing slot bytes directly so dormant NaN
  payloads survive, and cover touched unset holes below a populated high slot.
- Defer an inactive program-owned stack to the command using it. Validating it
  during an earlier unrelated command produces the wrong command-index error.
  Every command still needs preparation before any geometry or capture.
- Capture-index tests need a fresh undo step; an earlier program can leave the
  expected stamp present even if the tested program uses the wrong slot.
- Compare output normals before undo/redo or a full recomputation can repair
  them. The raw mesh oracle needs updateQueries between dabs; the raw grid oracle
  needs its union query radius restored before each call.
- Region tests need enough leaves that a smaller query omits moving owners.
  The coarse cube passed raw parity but could not test that distinction; retain
  an explicit outside-owner movement assertion. Remove temporary count tracing
  after diagnosing the fixture, retaining its evidence in the test logs.

## Input-delivery completion lessons

- A generated trailing move can retire the last real input to INBETWEEN. Grab and
  preview must consume real backlog samples before ignoring the generated move.
- Capture acquisition time in the producer, not callback arrival time. An RNA
  float narrows doubles; use the explicit Python double accessor for Event.time.
- Batch validation needs a per-row rollback for host scalar/input overlays.
  Invalid later rows keep earlier geometry but restore the rejected row's state.
- Cage execution must preserve inversion as well as device channels and restore
  swapped coordinate pages before propagating raw execution failure.
- StructProp supplies the effective owner on lookup. A property's retained owner
  pointer can be a dormant prior lookup cache; prepared reads use StructProp's
  owner and preserve that cache. Do not reject a dormant pointer as a live binding.
- Vector classes without operator== can compare via implicit pointer conversion.
  Compare position components or squared differences in geometry/undo tests.
- Current resolved falloff accepts finite zero-edge curve tables; the old
  Smoothstep/Linear-only capability note describes the earlier bounded slice.

## Generic authoring foundation

- New Scenes have ToolSettings but can have no Sculpt settings. Native adapters
  must expose unavailable parent capability and resolve locally without creating
  that data on read. Initialize test scenes explicitly and retain a missing case.
- Value and stack capabilities differ: native strength values can be available
  while the pressure adapter is pending. Never represent unavailable pressure
  with an empty identity stack or redirect a valid value write because of it.
- Effective-owner setters and metadata setters have different targets. Modes and
  stack inheritance belong to Brush; unified flags belong to Scene. Enforce the
  definition's owner restrictions for both kinds of writes.
- An isolated subpackage test loader avoids the bpy-dependent addon initializer.
  Blocking engine imports proves no new engine dependency; an automatically
  enabled addon may already have loaded the engine before a Blender test script.

## Generic authoring owner safety and storage review

- Registered ID PointerProperties use `ID.system_properties`; `owner.get()` and
  `owner.keys()` see `ID.properties`. Empty custom keys do not prove RNA pointer
  reads were nonallocating. `is_property_set()` checks system presence without
  creation, but does not validate types; ordinary RNA lookup can remove malformed
  backing properties. Inspection must not silently repair imported data.
- `record['layers'] = []` produces an integer array, not an IDProperty collection.
  Empty stacks need an absent-key encoding or an explicit typed constructor.
  Dictionary/to_dict round trips also lose opaque types, flags and UI metadata.
- Publish scalar values and definition-specific UI metadata in one transaction.
  Valid Python input alone does not guarantee later metadata publication succeeds.
- Brush IDs have `IDTYPE_FLAGS_NO_MEMFILE_UNDO`. Scene memfile undo deliberately
  preserves current ToolSettings. The headed Plan 4 test confirms both native
  Brush strength and native Scene strength/unified flags retain their current
  values while a Scene custom-property sentinel rewinds. Previous Scene owned-
  curve undo results must not be reported as Brush authoring undo coverage.
- Invalidate native adapter generations before AND after undo/redo/load, including
  load failure. Another pre-handler can create a new adapter against the old Main;
  post invalidation prevents it surviving with a reused Brush/session UID.
- Write eligibility must precede no-op detection. An unchanged request to a
  linked or override owner must still reject. Quantize float32 before comparing,
  and enforce actual native bounds even if a caller supplies a widened definition.
- An unused linked Brush may initially be indirect. A local Scene IDProperty
  reference promotes it to direct linkage for `override_create()` in the test;
  merely loading it can return None from that operator.
- WM notifiers do not themselves dirty Brush assets. A test of value and dirty
  isolation cannot prove the notifier recipient; the UPS owner correction has
  source-review evidence plus rebuilt runtime isolation checks, not message-bus
  instrumentation.

## Atomic scalar metadata lessons — 2026-09-17

- Logical metadata records can use custom IDProperty groups independently of a
  declared owner-aware CurveMapping bank. Keeping those namespaces separate
  avoids replacing curve storage when metadata roots are atomically published.
  This does not solve inspection/publication for the future declared curve bank.
- `owner.path_resolve()` returns a generic PropertyGroup for nested custom groups,
  including `id_properties_ui()`. For a button, resolve the parent group and use
  `layout.prop(group, '["value"]')`; passing the entire nested path as the property
  name on the owner prints a missing-property warning. Reacquire after publication.
- Blender's integer UI updater clears enum items when `items` is omitted. The
  atomic helper must explicitly preserve existing choices; ordinary updater
  behavior stays unchanged. Finite Python doubles may overflow float-backed UI
  fields such as `step`; reject after staging and before owner publication.
- Lossless native cloning with `LIB_ID_CREATE_NO_USER_REFCOUNT` preserves opaque
  data without Python conversion. Free both staging and the replaced root without
  user decrements only when operations cannot change ID-reference topology.
- Exact builtin parsing and direct C helpers avoid coercion/attribute callbacks.
  GC can still run during Python allocations: disable it across the bounded
  transaction and restore its prior state last, after all live owner access ends.
- Unregistering declarations alone does not prove authoring-module independence.
  Test a fresh process with the addon disabled and an import blocker during
  load/resave, then verify semantics in another fresh process.
- Wait for the actual build/install process to finish before another build or
  restage. Seeing an install heading in a log does not mean the process has
  released its logs or Windows DLL handles.

## Persistent stack lessons — 2026-09-17

- Keep ordered membership separate from stable device-keyed settings. A bounded
  scalar transaction can then update the entire stack without replacing groups
  or losing unknown metadata. Empty order makes retained entries dormant; it does
  not mean their payloads are valid or that re-add restores old known settings.
- Validate stack versions only when accessing stacks. Common record validation
  must let scalar/policy edits preserve newer stack sub-schemas opaquely.
- Whole-stack repair cannot override the atomic API's static-type guard. A static
  INT field cannot become DOUBLE even though both are scalars; test a late field
  mismatch to prove order/earlier edits roll back as well.
- Static-property gates need persisted nonempty data tests, not only write tests.
  Likewise independent owners require testing both directions: stack writes must
  preserve values and value writes must preserve both owners' stacks.
- Generated curve levels are finite doubles, not normalized [0,1] values or
  FLOAT32 samples. Only mix factors and step thresholds are bounded to [0,1].
  Persist negative/large levels exactly and defer evaluation/upload restrictions
  to the appropriate later capability boundary.

## Saved placement lessons — 2026-09-17

- Absence, explicit empty, and explicit defaults have different meanings. Persist
  override presence separately from retained per-location payloads, and test a
  new registry with changed defaults. Reset removes the override headers only.
- Reusing a general publication helper for reset can accidentally create a root
  through its schema/identity SETs. Check write eligibility first, then return
  before publication if both override headers are absent.
- SHA256 hexadecimal keys exceed Blender's 63-byte IDProperty key limit. The
  existing base32 representation fits. Preserve full location identity to detect
  malformed/colliding records, including dormant records being reactivated.
- Bound JSON order text before parsing, catch decoder recursion errors, validate
  the exact list/string shape, and separately validate active records. Scalar-only
  atomic DELETE must reject group/array header corruption without any publication.
- Placement must bypass native value/stack capability: a fresh Scene without
  Sculpt settings can still store its own UI placement metadata.
- Asset Save/Revert tests need an explicitly reacquired active asset context.
  Reusing the pre-Save brush handle/context caused Revert polling to fail in the
  placement harness; reactivation before editing/Revert resolved the test setup.
# Plan 4 declaration identity and negative type tests (2026-09-17)

- PropertyRNA addresses can be reused immediately after unregister/re-register;
  even the identical `_PropertyDeferred` can be reassigned. Use the fork's
  non-reused `curve_mapping_declaration_key`, plus owner and mapping lifetimes.
- `srna_from_self(dict, ...)` can crash under bundled CPython 3.13: builtin type
  `tp_dict` may be null and `pyrna_struct_as_srna` calls PyDict_GetItem directly.
  The new declaration API checks RNA subtype/dictionary and validates its own
  bl_rna wrapper, pointer, RNA_Struct and matching RNA Python type before lookup.
  Negative tests found and fixed this; do not broaden the existing helper here.
- Linking an external Brush asset already activated in the same Main can reuse
  its editable asset ID. A true linked/read-only fixture must be opened in a
  fresh process and assert `library is not None` and `is_editable == False`.
# Plan 4 final authoring gate lessons (2026-09-17)

- `ObjectModeType` re-registration failed even without undo. `pyrna_register_class`
  clears the parent RNA Python cache; a later public lookup recreated its base
  because `_bpy_types.py` had no persistent wrapper. Add the ordinary empty
  `_StructRNA`/`_RNAMeta` class like RenderEngine. Do not reconstruct addon mode
  classes or weaken validation. Regression tests must explicitly look up the
  public base between registration cycles; otherwise a null cache hides the bug.
- The new native `authoring_revision()` rejects evaluated/non-Main IDs with
  ValueError. OwnerGuard must normalize that into its established PropertyError
  contract. Final owner-safety tests exercise evaluated, linked and override IDs.
- A flag-only generic root with schema_version but no records is valid under the
  frozen-authoring plan. Update older schema tests to prove lazy record creation,
  while still rejecting present non-group records and future schema versions.
- Native diameter RNA has a diameter-specific subtype. Read the actual subtype,
  unit and bounds; do not hardcode DISTANCE. The native world-size setter currently
  leaves pixel size unchanged, while pixel edits rescale world size. Preserve the
  current behavior and restore both values exactly on authoring cancellation.
- Establish an in-custom-mode baseline when a harness expects undoing the first
  sculpt edit to remain in that mode. Otherwise the legitimate destination may
  precede mode entry, so an absent engine session is expected.
- At a limited history's hidden-only boundary, `ed_undo_poll` may remain true.
  `ed_undo_step_direction` discards the BKE false result and reports FINISHED even
  though there is no previous visible state. Check actual state and then verify
  retained redo, rather than treating every FINISHED result as an applied undo.
- Debug server exec captures stdout in its reply. A launcher marker printed
  inside exec is not visible in the Blender process log. Schedule the marker on
  a later Blender timer before quitting. Preserve debug action assertions too.
- The safe launcher writes `<prefix>.json`; scripts must use a distinct
  `<prefix>.checks.json` (or subdirectory) for their assertions, or the launcher
  overwrites them. Strip ANSI color sequences before verifying Node package logs.
- Installer idempotence must account for clang-format whitespace changes in
  copied C++ blocks. Normalize whitespace for the existence check before adding
  a block; never append another native method table entry on each install.

## Plan 5 curve cache lessons (2026-09-17)

- `construct_from_items` writes every vector element through ctypes. A validated
  primitive bridge can construct an empty owning vector, resize once and assign
  through `numpy()`, then dispose deterministically. Reflection accepts mutable
  vector-reference parameters; binding a const Vector reference tries to instantiate
  a const container binder whose resize method cannot compile. The checked methods
  still leave caller vectors unchanged.
- Native CurveMapping RNA does not expose every evaluation flag (`use_wrap` is
  absent). Use `authoring_native_curve_key(path)` for complete native fingerprints.
  Owned v1 fixes unsupported flags, so its visible point/handle/clip/extend fields
  plus validated runtime revision authorize reuse. UI selection does not rebake.
- Blender curve evaluation can differ from an endpoint coordinate by a few float
  ulps. Compare sampled native endpoints with a float tolerance. Keep analytic
  TWO_STEP branch comparisons exact, including a double threshold between floats.
- Publish pressure upload generations after checked scalar synchronization. A
  scalar write increments the global Brush configuration generation, even when
  unrelated to pressure; avoid identical writes and never reuse a memo after an
  external checked change. Warm Uniform memos must still validate their query.
- A headed timer testing load must use `persistent=True`; otherwise opening the
  fixture removes the test timer and the safe launcher correctly times out.
- Finish Blender test processes before restaging their loaded addon/DLL directory.
  Windows rejects removal while the runtime is mapped. Build configurations should
  run sequentially so generated sources and evidence are unambiguous.
- The native test framework checks outstanding allocations inside `test_end()`.
  Put owning test objects in a helper scope that exits before that call; local
  objects left alive in main appear as leaks despite normal eventual destruction.
- Preserve standard TypeScript generation formatting: run
  `format_checked_typescript.mjs` after native declaration generation, then the
  API package's installed `typescript/node_modules/.bin/tsgo.cmd`. The root engine
  package has no TypeScript compiler dependency.

## Plan 6 command integration lessons (2026-09-17)

- Mutable vector-reference reflection supports bulk buffers, but Python's current
  reflected call planner cannot copy a by-value litestl String. Named command stack
  calls use additive UTF-8 C APIs, like the existing typed command scalar API.
  Keep actual DLL invocation in the gate; successful C++ binding generation alone
  does not prove Python can invoke a method.
- litestl Vector has no const `data()` overload. A readonly span over a command's
  owned overrides uses the conditional address of element zero, with null for empty.
- When extending a geometry fixture with accepted dabs that intentionally move
  nothing, advance its expected stroke count too. Geometry and state restoration
  assertions should distinguish rejected dabs from accepted no-effect dabs.

## Plan 6 authoring snapshot lessons (2026-09-17)

- Native pressure curves already exist. `customize(..., reseed=False)` preserves
  that dormant native shape even when switching from a generated preset. Tests
  expecting a particular shape must explicitly reseed their own fixture.
- Tests directly calling addon unregister/register must leave it registered for
  Blender's normal shutdown. A successful test marker and exit code zero can
  still hide a teardown traceback; keep the safe launcher's traceback rejection.
- Preserve the native scalar domain when freezing semantic SIZE: its Definition
  is FLOAT32, while VIEW diameter is INT32. Validate the dormant world/pixel partner
  with its own RNA domain and compare the active partner with the resolved value.
- Typed evaluation clamps to representable endpoints, not arbitrary metadata:
  integer fractional limits use ceil/floor and FLOAT32 limits round inward.
  `prop_declarations.cc` already uses this rule. Rounding a clamped mathematical
  .1 back to FLOAT32 can otherwise leave the declared interval.
- Native FLOAT32 dynamics require narrowing after each arithmetic operation.
  Keep analytic thresholds double, preserve interpolation's endpoint branch,
  and abandon overflowing layers instead of throwing on runtime narrowing.
  The native clang toolchain disables contraction; exact-bit parity is testable.

- Prepared BSMOOTH must refresh dirty boundary classes after full preflight and before topology freeze, including after a missed/zero first dab. Raw first-dab hooks alone are not the oracle for that regression.
- Grid DefaultColumn routing checks names alone: prepared admission must additionally validate exact vertex/INT/read-only/no-use metadata. Test raw fallback separately from mandatory prepared policy.
- BSMOOTH projection is an authoritative static native member; Brush.writeProps only publishes common authored values. Tests must not dereference a nonexistent dynamic property for projection.

- Prepared non-accumulation must instantiate AccumOrig, not merely enable displacement stamping around AccumLive. Scratch replacement must use fresh manifests. The additive policy preserves co minus disp; smoothing can change this derived base and there is no height cap.
- Mesh beginStep does not increment strokeGen: hosts/tests call setStrokeGen explicitly. Grid beginStep owns its generation. Read sparse test attributes via safe_get; operator[] requires a materialized page.
- PowerShell redirected build logs may carry UTF-16: Get-Content piped into Select-String finds compiler diagnostics reliably when direct rg/Select-String misses them.

## Plan 6 mask undo lessons (2026-09-18)

- Mask edits prolongate deltas into finer authored levels. Capturing only the
  edited level cannot undo those changes; cache invalidation cannot repair storage.

- Previously absent finer levels seed their whole allocation from the edited
  coarser level. Preserve allocation absence with owning state swaps, including
  debt and compressed data; allocated levels need only occurrence-grid blocks.
- Name and metadata do not establish channel identity after deletion/recreation.
  Runtime incarnation tokens also protect level replacement, debt and live masks.
- Reading a logical-zero absent mask level must not allocate it. Invalidate finer
  domains before an owning seek and reacquire pointers before testing rebuilt data.
- Blender receives a fixed undo charge at push. Reserve a stroke-created finer
  allocation before undo transfers it to the log; counting only currently held
  bytes undercharges that later transfer.
- BrushProgram.setCommandFloat appends an override; it does not replace one.
  Raw per-dab reference programs must clear/rebuild rather than append duplicates.
- Native BrushProp is not a reflected enum. Use the addon's fixed property IDs;
  internal strokePathCount is likewise unavailable on the reflected Brush.

## Plan 6 automasking lessons (2026-09-18)

- Prepared mesh calls need an open executor transaction. The addon's fresh
  MeshLog has no active mesh binding, so accept null until an operation binds it;
  validate any existing binding, the log pointer and the unfinalized step ID.
- A scope that restores only executor settings must not truncate new named
  kernel slots published by an accepted standalone call.
- Cavity cache support is each command's radius, including its nonaccumulating
  base coordinates. The shared program leaf region is only a conservative query.
- Long-lived BFS scratch must clear stamps when its uint32 token wraps.
- Mesh export remap buffers require vertex capacity, not live vertex count.
  Prefer the addon's existing dumpVertCo helper for position-only test output.
- Multires_levelPositionsOut requires Multires_levelSampleCount entries of
  three floats, including seam replicas. Multires_levelVertCount is too small
  and using it corrupts memory. Both mistakes were corrected in the test harness.

### Prepared preludes and native test ownership (2026-09-18)

- Test generated C++ compilation as well as certificate strings. Parenthesized
  named uniform lvalues must still lower to setEvaluatedNamed; a getter expression
  cannot be assigned to. Whole-coordinate writes use CoProxy's supported API.
- Generated names such as any_moved can collide with DSL locals and silently
  suppress spatial updates. Reject reserved generated names before code emission.
- Mesh factories allocate with litestl::alloc::New. Pair them with alloc::Delete,
  never C++ delete. A mismatched release crashed the new fixture after its capture
  and kernel had already succeeded; it was not a missing-DLL failure.
- Wait for the build session to finish before testing. The dispatcher's early
  "ninja: no work to do" can refer only to the compiler-tool phase, while the main
  native build has yet to compile/link the changed regression executable.

### Unbounded execution checks (2026-09-18)

- A standalone cavity oracle must ensure the mesh ring1 cache before calling
  MeshCavitySrc; executor setup cannot initialize adjacency for an earlier oracle.
- A convex grid can saturate every cavity factor. Use asymmetric geometry and a
  smaller factor, and assert that the expected factors actually vary.
- Blender's thread can flush subnormal binary32 values during Python conversion
  before the DLL sees them. Construct tiny probes in binary64 and record the
  value received by Brush before attributing a zero result to the kernel.
- Near-origin Kelvinlet rounding can exceed the field's proven unit row-sum bound.
  Test multi-component FLT_MAX forces as well as purely transverse forces; the
  anisotropic sum exercises a different overflow from the isotropic coefficient.
- Test FTZ and DAZ separately as well as together. A compiler can fold a direct
  float-to-double comparison using IEEE assumptions and defeat a DAZ-only probe.
  Volatile input and promoted result force the conversion being tested to occur.
- A headed startup script can finish its assertions yet hang after an immediate
  `quit_blender()` call. Defer quit with a timer after startup, as the existing
  headed modal tests do. Retain the failed launcher record: a printed success
  marker alone does not count as a passing process-level gate.

### Repository license boundaries (2026-09-18)

The addon's GPL/Blender SPDX convention does not extend into the MIT-licensed
engine submodule. Check each repository's LICENSE and existing source conventions
before adding notices. Removed 38 incorrect headers introduced during this task,
preserving the rest of each file byte-for-byte and retaining notices already in
engine HEAD. The correction manifest is `tests/engine-header-correction.json`.
Scoped the addon CLAUDE.md rule explicitly and corrected the engine-file helper
template that could recreate the mistake.

### ENHANCE acceptance fixtures (2026-09-18)

- Native nonaccumulating test fixtures must set a nonzero stroke generation,
  matching the addon. Generation zero can skip initial displacement-page writes
  because fresh stamps are also zero; later deformation then accesses an absent
  page. The Windows debugger localized this fixture omission to CoProxy::commit.
- `BrushProgram::setCommandFloat` appends legacy overrides. Use
  `setCommandScalarChecked` to replace a radius while testing repeated dabs.
  Appending another entry correctly fails duplicate-override preflight.
- The independent ENHANCE oracle reads authoritative edge endpoints from
  `mesh.e.vs`; vector splat zero is `float3(0.0f)`, since integer zero also matches
  the vector pointer constructor.

### Prepared grab C API exports (2026-09-18)

New C API implementations also need declarations in stroke_inputs.h and entries
in source/brush/CMakeLists.txt's wasm_add_symbols list. That list controls native
DLL exports too. Native C++ tests can pass while ctypes cannot find the function.
The installed grab test caught the omitted image exports. Rebuild, restage and
run the installed test plus package smoke after fixing the export list; a basic
addon-enabled check can succeed despite optional engine initialization errors.

### Prepared preview rollback (2026-09-18)

- Preview row snapshots must omit TOPO connectivity columns. Frozen topology
  releases those pages, and topology chunks already own their rollback. Capturing
  or restoring the pages through the data snapshot produced thousands of warnings.
  The revised native matrix and legacy topology-preview tests pass without those
  warnings in the prepared suite.
- Restored coordinates do not invalidate the executor's leaf base-stamp shortcuts
  or first-contact caches. Reset them when discarding a prepared preview group.
- A flat patch can make SMOOTH/ENHANCE a valid no-op, and strong cavity suppression
  can hide every deformation. Use nonflat geometry and a neutral cavity factor
  for the native movement assertion; separately compare nonconstant cavity in
  installed host fixtures.
- A modal setup can create the mesh executor while a multires slot is still
  lazy. Bind that existing executor when materializing the slot; otherwise its
  tree stays null even though the session has a valid tree. Mesh-path stroke
  startup must materialize independently of whether a draw provider exists.
  Grid and cage-only routes retain their lazy behavior.
- Scripted headed gesture fixtures must push a scene baseline before testing
  undo. Timer-driven scene construction does not automatically produce the same
  undo history as interactive object creation; without the baseline, undo can
  restore the startup cube instead of the test object.

### Prepared attribute capture (2026-09-18)

- The current litestl OrderedSet::add returns false even after insertion. Use
  Set when the insertion result controls capture; otherwise no rows are saved.
  The native multi-layer and Blender paint undo fixtures caught this misuse.
- Snapshot helpers for frozen mesh execution must not read live edge-link pages.
  The debugger identified the fixture's preparedDyntopoState edge walk as the
  crash site; attribute tests now snapshot positions and typed data directly.
- clang-format sorts nearby include directives. A fixture header that uses
  another fixture's helpers must include that header itself, rather than relying
  on the caller's include order.

### Prepared cage smoothing (2026-09-18)

- COLORSMOOTH's live-disk neighbor variant must keep topology links live. Reuse
  CommandExecutor.brushNeedsLiveLinks when bypassing the legacy execBrush loader.
  The debugger identified a LiveDiskNbr.range access violation in the initial
  checked draft; native and installed tests pass after applying the same policy.
- Host undo fixtures should enter actual SculptCore mode, not call convert.enter
  while staying in Object mode. Depsgraph handlers may retire the latter session
  during flush, clearing its multires map before redo. The real mode lifecycle
  and headed Shift-smooth tests cover the corrected fixture.

### Cavity traversal after dyntopo collapse (2026-09-18)

Live mesh vertex count is not a bound on raw vertex IDs after deletion. Cavity
BFS visit stamps and prepared factor columns must use vertex capacity. Count-sized
scratch produced intermittent nonaccumulating cavity differences without changing
topology. Exact intermediate-dab comparisons and eight repeated native runs pass
with the capacity fix. A passing retry alone does not resolve intermittent failure.
Use explicit UTF-8 for source edits; some older evidence files contain isolated
CP1252 punctuation, so preserve existing bytes when appending evidence.


## Generic stroke integration - 2026-09-18

Autosmooth programs must use one override representation per property. Combining
legacy setCommandFloat with setCommandScalarChecked for strength creates duplicate
command overrides and correctly fails prepared validation (status 64). Generic
program construction now uses the typed setter from the start. Command strength
dynamics remain native, with an explicit command stack over the autosmooth base.

GridStrokeLog undo at the highest multires level previously failed to advance
maskGeneration: it notified only when finer-level snapshots existed. A resident
slot therefore appeared current after undo; flush folded its old column over the
restored store mask. Notify whenever a captured mask leaf is restored. Native
revision assertions and all eight actual mesh/grid Mask gestures pass, including
Blender undo/redo with a materialized slot.

Generic startup previously installed legacy local tables/stacks before replacing
them with effective-owner snapshots. Keep those installation paths separate;
otherwise dormant settings can cause redundant uploads. The existing headed
cache driver now rejects legacy installation in generic mode and checks zero
rebakes/uploads on an unchanged next stroke. After editing strength, size and
strength no longer share a native response, so a full cache reset bakes four
distinct curves instead of the original three.

Typed probe bindings require `tests/assets/typed_extras` in the native build's
extra kernel directories; the production DLL intentionally omits these probes.
The probe's candidate-count assertion also needed to exclude ENHANCE's two
kernel-specific settings. Its complete execution matrix passes with that explicit
exclusion; a compiler-only run without the probe is not equivalent coverage.

## Generic radial authoring - 2026-09-18

Cancel modal property edits before unregistering authoring/curve services. A
draw-handler removal alone leaves the native owner edit scope alive. Keep an
explicit active-operator list, close its scopes on load/undo/redo and addon
shutdown, and let a later queued modal event return cancelled without touching
retired state. Real F/Shift-F events exercise this teardown and owner changes.
Treat the Shift-F shortcut modifier separately from a subsequent precision Shift
press; otherwise strength starts unexpectedly at one tenth of the drag speed.
Keep a fractional drag accumulator separate from the rounded integer size.
Rounding each individual precision movement loses small events; the fixture
uses ten consecutive one-pixel moves to retain this coverage.

## Generic property rows - 2026-09-19

Blender Python operator calls suppress undo unless explicitly enabled. Tests of
operators that use authoring scopes must call, for example,
`bpy.ops.sculptcore.property_value('EXEC_DEFAULT', True, ...)`. Otherwise the
native scope correctly rejects the pending/nested undo context. Real UI events
do not need this Python-call override.

The Properties Active Tool tab uses `ED_view3d_buttons_region_layout_ex`: it
draws View3D Tool-category panels, not ordinary Properties panels with context
`tool`. Register an appropriate View3D panel and restrict its poll to Properties
when it should appear only there. Transient Python-backed search properties need
an explicit redraw update callback, including for scripted changes.
For actual widget fixtures, separate hover, mouse press and release with short
timer callbacks. Sending all three in one timer turn reopened a just-cancelled
popup inconsistently; tracing showed no second operator invocation. The split
events exercise actual numeric cancel/confirm and inheritance buttons reliably.

## Inline property widgets - 2026-09-19

- A Python `get`/`set` property on the WindowManager is the way to draw an
  engine/store-backed value with a real slider: the getter resolves the
  effective owner per draw, so nothing is cached that could go stale.
- Blender calls the setter on every mouse move of a drag (`data->interactive`),
  and pushes its own undo once per activation only for owners that pass
  `ID_CHECK_UNDO` — never for the WindowManager. A setter that pushes its own
  step therefore pushes one per move. A fork merge keyed on a per-activation
  gesture id (`apply_but`) worked, but was reverted the same day when brush
  edits stopped pushing undo at all (below); don't rebuild it without reading
  that decision first.
- Setters have no `report()`; print to the console and write nothing.
- Never `area.tag_redraw()` the 3D viewport from a property setter: that
  re-renders the sculpt mesh on every slider move, which is what made the
  inline sliders drag on large meshes. Blender's own brush edits only redraw
  the paint cursor (`NC_BRUSH`/`NA_EDITED` → `ED_region_tag_redraw_cursor`).
  Tag the sidebar/header regions (`region.type != 'WINDOW'`) and the
  Properties areas instead. The Python side is cheap by comparison: setter
  ~0.7 ms, getter ~0.26 ms, the All Brush Properties draw ~10 ms per redraw.
- Escape during a drag re-applies the original value through the setter.
- Simulated events land asynchronously: a check phase .5 s after a drag whose
  last event fires at .5 s races it. Give event-driven phases a settle phase.

## No undo for brush property edits - 2026-09-19

- Decision: vanilla sculpt-mode parity (#71434). Every `authoring_edit` in the
  addon is `undo=False`; the scope only snapshots for cancel/disable rollback.
- Why memfile undo could never cover it: the active brush is a linked asset and
  memfile undo keeps linked IDs as-is (`read_libblock_undo_restore_linked`).
- Why the authoring step was worse than nothing: it rode on a memfile push
  (`use_memfile_step`) whose encode runs the mode's full mesh flush, so a slider
  drag flushed per move; `interactive()` refused the edit whenever global undo
  was off or an undo group/operator was open (edits silently did nothing); and
  Ctrl+Z after a tweak undid the tweak instead of the stroke.
- Blender preserves the whole `ToolSettings` across memfile undo
  (`scene_undo_preserve` swaps it back), so unified strength/size, size mode and
  cavity settings/curves on the Scene are never undone either. Only Scene
  ID-property records (generic values, stacks, placement stored on the Scene)
  revert when the user undoes something else. A first test draft assumed all
  Scene data reverts and failed on unified strength.
- Testing "no step": push a marker memfile step, change a Scene field, push the
  baseline, edit, undo. Landing on the marker proves the edit pushed nothing.
  Memfile undo reloads the Scene, so Python references to it (and to
  `unified_paint_settings`) taken before the undo are stale — look them up again.
- `sculptcore_addon/convert/*.py` imported the top-level `undo` module as
  `from . import undo` after the package split; every multires enter raised
  `ImportError`. Fixed to `from .. import undo`.

## Undo back into the mode crashed the viewport - 2026-09-19

- Crash: `EXCEPTION_ACCESS_VIOLATION` in `extdraw_nodes_get`
  (`engine/source/spatial/c-api/external_draw.cc`) from `eevee sync_sculpt`,
  after enter SC → Tab (edit) → Tab → enter SC → undo ×3. Read the report at
  `%TEMP%lender.crash.txt`; the operator log at its top gives the sequence.
- Mechanism, two halves. (1) `Session.free()` freed the tree but only
  `convert.exit_` unregistered the external-draw entry, so a session freed by
  `handlers._reconcile` (an undo took the object out of the mode) left the
  registry pointing at a freed tree. (2) Memfile undo keeps `OB_MODE_CUSTOM`
  on the restored object (object.cc only clears it on file load) and the fork
  runs no enter callback and no `refresh` for a custom-undo mode, so an undo
  landing on an in-mode step gave an object that is in the mode by DNA with
  no session — and the next draw asked the provider for the stale tree.
- Fix: `Session.free()` unregisters `draw_key` first; `handlers._on_undo_redo`
  runs `_reenter_restored()` (rebuild the session of any in-mode object
  without one, adopting `custom_mode_state`). Regression:
  `claudeMemory/scripts/test_undo_mode_reentry.py` (headed).
- Scripted operators push no undo step unless called with `undo=True`
  (`bpy.ops.x('EXEC_DEFAULT', True, ...)`); without it `ed.undo` polls false
  ("context is incorrect") and the sequence cannot be reproduced.

## Curve popup lifetime - 2026-09-19

Native CurveMapping dialogs reopen with the selected point's X field focused.
Leave that field before a test's graph insertion; otherwise the first click can
finish text entry without changing the curve. Assert the mapping changed before
testing Cancel or shutdown, so an inert click cannot produce a false pass.

The stack-widget shutdown gate exposed a fork crash in `bpy_class_call`.
`refresh_for_srna_unregister` closes popups with a temporary context; a Python
cancel callback installed it as `bpy.context`, then unregistration freed it.
The next custom-mode exit callback read freed context data. Restore the previous
Python context after the callback, matching the existing scoped string-execution
helper. The same headed gate now edits a native curve, disables the addon with
the dialog open, verifies rollback, and re-enables it without a crash.

## Placement persistence - 2026-09-19

An external active brush may still be unresolved immediately after a background
file load. A `.blend` placement fixture must explicitly retain its edited Brush
data (the headed driver saves a fake-user copy) and reacquire it by name. Do not
interpret an absent active asset pointer as lost metadata or claim that this
copy/reload check verifies external asset saving.

## Window and UI-authoring fixtures - 2026-09-19

Use `wm.window_new_main()` when testing independent window scenes. Ordinary
`wm.window_new()` makes a child that follows its parent's scene; assert the
windows' Scene identities before testing owner routing. Undo-enabled authoring
operators require a headed event-loop context, not a background startup call.
Keep direct-store background execution coverage and use the same geometry
fixture from a timer with a View3D override for the UI-to-engine boundary.
Placement-dialog widget coordinates changed when the fourth location was added;
inspect the screenshot and target the labelled checkbox, retaining the assertion
of the exact resulting positions rather than weakening it.

## Frozen migration fixtures - 2026-09-19

Reading an unset generated RNA property can create a ghost IDProperty with the
current registration default. Use `system_property_scalar` for legacy authored
presence; migration must not import that ghost or the replacement DLL's default.
The existing frozen fixture now re-registers deliberately changed defaults and
verifies both migration and fresh reload against the frozen declarations.
To test a malformed raw legacy type, delete its existing scalar first: assigning
a string over an existing Float IDProperty is rejected by Blender before the
migrator can inspect it.

The fork's Brush type has `IDTYPE_FLAGS_NO_ANIMDATA` and exposes no
`animation_data`; test actual `driver_add`/`keyframe_insert` rejection before
designing animation migration. Driver variables on other IDs can still read
Brush paths. RNA transform getters used by those variables must read only the
supplied ID's storage: main-thread-only authoring guards are inappropriate in
dependency-graph evaluation or temporary Mains. Driver evaluation may differ by
one float32 ULP, so compare its numeric result with an appropriate tolerance.

`id_properties_update_atomic` rejects duplicate paths. When migration and a
generic edit share one transaction, deduplicate exact paths with the explicit
edit taking precedence; do not publish migration separately before a failing edit.
Owned curve references include their revision and must be reacquired after
changing a point before installing them into a stack.

When consolidating samplers, retain an independent parity oracle: comparing two
callers of the same implementation no longer checks the algorithm. Python's
compensated `sum` can differ in the last bits from sequential float addition;
the overlap oracle allows 1e-14 while the two production callers remain exactly
equal. Count overlap builds at the shared cache, not a retired session memo.

## Plane-brush frame parity (2026-09-20)

- **A Bash heredoc that writes source containing backslash-n string escapes
  is unreliable**: the tool mangles the escape into a real newline inside the
  literal (a `write("...")` or `fprintf` whose string ends in the escape),
  which breaks the C++ string and reads as "unexpected EOF" or "expected
  expression". Write the patch script to the scratchpad with the Write tool
  and run `python <path>`, or use the Edit tool for the line itself. (This
  very bullet was mangled the same way when first written through a heredoc.)
- `ctest` is not on PATH in the engine; `node make.mjs test [name]` is the
  runner (no name = the whole suite; the summary is at the tail).
- clang-format reorders includes, so a patch script anchored on an include
  block written before formatting misses; anchor on a line that formatting
  does not move.
- `litestl::alloc::Delete` is the deleter for `createCube` cages (not
  `litestl::util::alloc`).
- A grids non-accumulate stroke recovers the base as `pos - disp`, which is
  one ulp off after several dabs — compare with a 1e-6 tolerance, not
  bit-exact; the mesh path's stamp reads the base directly and stays exact.
- The plan's non-accumulate rule ("plane family only") contradicted the fork:
  `sculpt_update_cache_invariants` clears `cache->accum` for *every*
  `supports_accumulate` brush with the toggle off. Check the actual brush
  source before changing a derivation a plan asserts.
- The Blender-side plane tests fail on the vendored DLL as soon as
  `engine.py` declares a new export (`function 'GridStroke_setPlaneFrame' not
  found` at engine init, reported as "engine prop generation unavailable"):
  run the addon suites with `--dev-engine` until the submodule bump restages
  the DLL. `run_brush_tests.py` gained the flag for this.
- `test_property_snapshots.py` (not in any suite) fails at "engine defaults
  remain unset with frozen generic domain" before and after this change —
  pre-existing, not a plane-frame regression.
- **Never benchmark `engine/build/native/`.** Its toolchain
  (`build_files/native-clang.cmake`) sets `-ffp-contract=off` so geometric
  predicates stay arch-stable under ctest; the shipped DLL is the
  `build/python` one, built with clang's default contraction. An A/B whose
  B side pointed `SCULPTCORE_CAPI_PATH` at the native DLL measured no-FMA
  against FMA and reported the plane-frame change as +21 % before any of it
  was attributed. `run_blender_test.py --dev-engine` uses the native DLL,
  which is right for correctness gates and wrong for timing; for a
  benchmark set `SCULPTCORE_CAPI_PATH` to `engine/build/python/` by hand.
- A per-dab normal refresh before an accumulating AREA gather is not parity:
  Blender's `calc_area_normal` reads whatever the draw update left
  (`sculpt.cc` refreshes normals per step only for external render
  engines), so the gather lags one frame there too. The refresh was removed
  and (d') in `test_plane_frame.cc` models the frame cadence with an explicit
  `updateNormals()` between dabs instead.
- The plane-frame gather is one more full pass over the dab's verts per dab
  (Blender pays the same). Serial it cost measurably; it now runs one
  partial per node/leaf under `task::parallel_for` and reduces in node order,
  which keeps the sums run-deterministic (a threaded `float3` reduction in
  arrival order would not be).
- `patch_inventory.py`-style edits of `generic-brush-inventory-v1.json` must
  write bytes (`newline=''` or `'wb'`): a text-mode write on Windows makes
  the file CRLF, the generators pin the sha of *those* bytes, and the next
  `git stash`/checkout normalises the file back to LF — after which
  `authoring/inventory` fails on the sha with nothing visibly changed.
  Regenerate (`generate_native_authoring.py`, `generate_native_coverage.py`)
  from the LF file and convert their own CRLF output to LF.
- A memory-pressure kill of a background bench leaves its Blender and node
  children running and the build tree staged on whichever addon side it was
  mid-pair; kill the orphans and `stage_test_addon.py` before trusting any
  later Blender run.
