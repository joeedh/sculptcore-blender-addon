# Plan 3: typed extra-kernel emission

Status: complete for this bounded gate, 2026-09-16. Plan 3 remains open.

## Scope and decisions

Complete the compiler path from declared float/int/bool extra fields to the
existing typed working stores. Preserve float slot order and API signatures.
Integer/boolean dynamics require explicit `@dynamic`; context fields remain
working state only. This gate precedes checked configuration/bindings, which
will use the real compiled typed fixtures. Full prepared execution and input
delivery remain later Plan 3 work.

1. Collect complete scalar store declarations in registry mode. Validate names,
   types, metadata and cross-kernel compatibility. Assign dense slots separately
   for FLOAT32, INT32 and BOOL, preserving first appearance within each type;
   enforce the existing 65536 limit per type. Emit typed defaults, immutable
   descriptors, lookup and presence-aware initialization. Reject nonscalars.
2. C++ emission selects typed reads, getters, evaluated setters and property
   loads. Preserve exact integer defaults including 16777217 and INT32 limits.
   Simple/compound host assignments use evaluated setters, never authored
   writes. Validate metadata for stored context fields as well as uniforms.
3. GPU appended uniform packing uses four-byte float/int32/u32 scalars. Bool
   is explicitly converted to uint32_t before memcpy. WGSL uniform bool fields
   use u32; expression reads convert with != 0u, including native invert.
   Local expression bool types remain bool. Preserve existing scalar offsets
   and 112-byte overflow checks. Context wire bool uses the same conversion;
   existing lack of runtime extra GPU/context dispatch is recorded honestly.
4. Add isolated typed extra .sbrush fixtures under tests/assets/typed_extras.
   Build a test-enabled native DLL using explicit extra dirs ../brushes and
   that fixture directory, so registration/descriptors/factories and executor
   template instantiations are the actual global registry, without alternate
   registry definitions in linked translation units. Do not vendor that DLL.
   Test dynamic and static fields, authored/cache separation, exact integer
   defaults, host writes, bool behavior, repeated initialization, float order,
   type conflicts and invalid metadata. Exercise mesh and grid generated CPU
   consumers with actual values; verify shader output with available validators
   and packed-byte tests. No claim of GPU extra dispatch from codegen alone.

## Gate

Fresh CPU/registry and GPU/test-seam adversarial reviews; fold surviving findings.
Standalone compiler codegen, explicit-extra native build, typed-extra suite and
the existing fourteen native regression suites. Record exact fixture-enabled
build command, hashes, branch markers and scope. Restore the addon-only native
build after fixture evidence and rerun affected regressions; future bindings
may deliberately rebuild fixture DLL in a separate gate. Update the parent
task list and Plan 3 evidence; do not mark Plan 3 complete.

## Fresh adversarial review corrections

CPU/registry and GPU/test reviewers inspected the actual consumers. Folded:

- Share the complete field semantic validator between registry and C++ modes;
  registry currently bypasses C++ validation. Reject duplicate field names even
  when identical within one kernel, reserved/native mismatches, invalid context
  metadata and explicit dynamics on context/nonscalar fields in both modes.
- Use one-command mesh/grid programs. The current standalone grid applyDab
  loads only common properties; full single-command preparation remains open.
  Configure typed property dynamics through the native typed core for this gate;
  legacy name-based configuration still rejects int/bool until the next slice.
- Explicitly emit fixture WGSL and validate with C:/dev/tint/tint.exe and
  C:/VulkanSDK/1.4.350.0/Bin/spirv-val.exe. Extra-dir CMake only emits C++.
  Require real vertex body consuming bool uniforms/context/native invert and
  local boolean expressions; host-only WGSL stubs do not satisfy this gate.
- Call generated fixture GPU pack directly: production dispatch only knows
  builtins. Assert four-byte bool 0/1, neighboring offsets and exact int bytes.
  Integer range packing intersects INT32 then rounds endpoints inward, with
  no intermediate float. Context bool has no runtime extra-context marshaller;
  its coverage is declaration/read codegen and shader validation only.

## Implementation and evidence

- Shared semantic validation now runs in C++ and registry modes. The factory
  stem also uses a shared function: a mixed-case fixture exposed an existing
  registry/class-name mismatch. Store declarations retain exact typed defaults,
  per-type indices, descriptors and initialized presence. Typed evaluated loads
  and host setters leave authored values unchanged.
- GPU int packing uses int32_t and inward-rounded integer range endpoints;
  bool packing writes uint32_t 0/1. WGSL bool wire reads convert with != 0u.
- `node make.mjs codegen` passed; ../tests/typed-extras-codegen.log. Subsequent
  native builds also rebuilt and linked the standalone compiler after fixes.
- `node make.mjs build native --kernels-extra '../brushes;tests/assets/typed_extras'
  -j 8` passed; ../tests/typed-extras-build-3.log. Earlier failed attempts are
  retained: factory naming, ambiguous test string/vector constructions, and a
  WGSL-reserved fixture local name were corrected.
- `python claudeMemory/scripts/run_typed_engine_gate.py --prefix typed-extras
  --extended-registration --named-storage --typed-extras`: 15/15 suites passed.
  ../tests/typed-extras-results.json records exact commands, executable hashes,
  and required global-registry/mesh/grid branch markers.
- Fixture-enabled DLL SHA256:
  5957c22e614614fc36f1465f44a6c066ad0292b4dc0ce5e320c1174a4d72bde5.
- `python claudeMemory/scripts/test_typed_extra_compiler.py` passed: real vertex
  WGSL through Tint, SPIR-V through spirv-val, 16 semantic CLI rejections across
  both modes, compatible sharing and three cross-kernel conflict cases.
  ../tests/typed-extra-compiler/results.json and hashes.json record evidence.
- Native fixture covers exact 16777217 and INT32 extrema, true/false defaults,
  high-slot initialization, static/context descriptors, local authored writes,
  read-only atomic failure, evaluated cache isolation, host simple/compound
  writes, packed scalar offsets/canaries and inward integer range clamps.
  Mesh and grid programs run four dabs with independently checked geometry:
  first/last move by 0.125; bool pressure disables the second; integer tilt
  changes 16777217 to 16777218 and disables the third. Authored values persist.

This gate configures typed stacks through the native property core. It does not
claim typed legacy/reflected configuration, standalone-dab preparation, GPU
extra dispatch, context GPU marshalling, or headed addon delivery. Plan 3 remains
open. No fixture runtime was vendored or installed in Blender.

Addon-only restoration passed with `node make.mjs build native --kernels-extra
../brushes -j 8`; ../tests/typed-extras-addon-build.log. CMakeCache records only
the addon brushes directory. The restored gate passed 15/15 suites with
`--extended-registration --named-storage --compiler-boundaries`; its typed-extra
executable explicitly reports compiler boundaries only. This restoration run
does not replace the separate fixture-enabled geometry evidence above.
Results: ../tests/typed-extras-addon-results.json.

The exact-DLL legacy Python smoke also passed;
../tests/typed-extras-addon-bindings.log. Restored DLL SHA256:
a0ef50a2a74aadb2ae1669d35e53243f32b48ac0eb30b7a96acb060616eb0ee3.
Touched compiler/CMake files pass diff whitespace checks; new native tests were
formatted and all added source/helpers carry SPDX headers.
