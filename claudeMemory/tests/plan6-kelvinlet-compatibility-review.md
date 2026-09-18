**Compatibility verdict: hold admission pending concrete lowering and execution tests.** The packet supports the algebraic rewrite’s general direction, but does not establish that the proposed DSL builds or preserves execution behavior. These are compatibility findings; the independent numerical review should determine the arithmetic guarantee.

Only the supplied packet was reviewed. `CLAUDE.md`, the parent plan, compiler statement lowering, and executor implementations were not supplied.

1. **The proposed four-argument `max` cannot be used literally.**  
   `intrinsics.cc:209–216` defines only a two-argument scalar intrinsic. The supported spelling is:
   ```text
   max(max(abs(r.x), abs(r.y)), max(abs(r.z), eps))
   ```
   Component access and the proposed vector/scalar operations still need actual compiler coverage. This is a concrete correction to the proposed notation, not evidence that the entire rewrite is unsupported.

2. **“Continue on zero” needs an explicit DSL and generated-code contract.**  
   The existing generated CPU kernel appends every visited vertex to `affected_verts` and sets `any_moved` after the DSL body (`kelvinlet.brush.gen.h:59–79`). A loop-level `continue` bypasses those operations. A conditional around the displacement computation may leave them intact. Those alternatives have different observable behavior.

   The packet does not show whether a vertex-stage `continue` is legal or how it lowers on GPU backends. Do not substitute a stage `return` without verifying its scope either.

   **Minimal correction:** specify the supported early-exit construct and its bookkeeping semantics. Test a wholly excluded node and a mixed node for unchanged positions, affected-vertex tracking, update flags, and undo behavior. Include the applicable iterator policies: the supplied iterator interface alone does not prove that skipping the body skips all writeback.

3. **An early cutoff check is only as reliable as the existing window calculation.**  
   `brush_command.h:359–367` computes:
   ```text
   R = radius * extent
   d = length(co - surfacePos)
   t = clamp((R - d) / (0.2 * R), ...)
   ```
   Finite inputs do not establish finite intermediates here. An overflowing `R` can produce `Inf/Inf`; an underflowed `R` returns the disabled-window value `1`; an underflowed transition width can produce `0/0`. `window == 0` catches none of the resulting NaNs.

   The plan already calls for extent/cutoff/transition-width validation, but the packet does not show that implementation or its placement. **Make that parent work an explicit admission dependency.** Validate the actual evaluated float products, before mutation, and test disabled extent separately from a positive extent whose product becomes zero. Keep the window centered on `surfacePos`, while the field remains centered on `grabFrom`.

   Distance overflow is an existing window limitation. It should not be reported as introduced by this correction, but neither does moving the window earlier fix it.

4. **Prepared scalar validation does not validate the proposed vector preconditions.**  
   The manifests contain `mu`, `nu`, and `radius`; preparation handles scalars, and `ScopedBrushWorkingValues` saves scalar working values plus the cavity curve (`brush_preparation.cc:441–455`; `brush_program_preparation.cc:233–310`). None of that establishes finite `grabFrom` or `grabTo`.

   **Minimal correction:** put vector checks in command-wide execution preflight, against the values execution will actually consume, before publishing configuration or beginning mutation. Preserve validation on zero-count calls. Do not add vector state as scalar properties or mutate it merely to validate it.

   The same applies to extent snapshots: the generated GPU packer reads live `brush.unboundedExtent` (`kelvinlet.brush.gen.h:120–121`). Snapshot behavior must be demonstrated by the parent execution work, not inferred from scalar preparation.

5. **A shared DSL expression does not establish raw/prepared or CPU/GPU domain parity.**  
   Prepared material values are range-validated. Raw CPU host code clamps `mu` only from below, whereas GPU packing also clamps it to `100` (`kelvinlet.brush.gen.h:29–40, 122–130`). Thus raw CPU/GPU already differ outside the declared material domain.

   Likewise, the supplied positive-radius reciprocal check appears in program preparation (`brush_program_preparation.cc:218–224`); it is not evidence that every raw entry point rejects the same radii or skips zero radius.

   **Minimal correction:** state that parity tests use identical effective inputs within the validated domain. Demonstrate zero-radius handling for every path covered by the claim. Treat broader raw-input sanitization as separate scope unless explicitly required.

The prepared certificates themselves need no apparent expansion **if host and reduce stages remain unchanged**. Their documented purpose is state preservation and definite initialization, not numerical finiteness. Moving `max`, conditionals, or other calls into `reduce` would encounter the restricted proof grammar (`prepared_preludes.h:108–180`) and can remove eligibility. Keep this correction in the vertex stage and assert that regenerated eligibility flags remain true.

Before admission, require:

- DSL compilation and actual target compilation/validation for C++, WGSL/SPIR-V, CUDA, HIP, and OpenCL as applicable—not just successful source emission.
- CPU raw/prepared comparisons using the same evaluated inputs, plus applicable GPU comparisons.
- Exact-zero window tests proving field and texture evaluation are bypassed; boundary and differing-center tests.
- Invalid late-command and zero-count tests proving atomic rejection, plus success/failure working-state restoration and independent material dynamics.
- An independent double reference using the original mathematical formula, with float-rounded inputs and displacement checks so position rounding cannot hide errors.

Optional refinements include correcting the source comment that says `nu → 0.5` makes `4*(1-nu)` vanish—it does not—and documenting the expected rounding change. Existing CUDA/HIP/OpenCL automask omissions are explicitly recorded in `intrinsics.cc:87–88`; this numerical patch should neither silently expand its scope to fix them nor claim complete backend behavioral parity.