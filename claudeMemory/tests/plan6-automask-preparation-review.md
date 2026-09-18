**Preparation verdict: revise before implementation.** The plan states most required outcomes, but leaves several source-level integration decisions unresolved. These are preparation blockers, not findings about code that has already been implemented. Review is limited to the supplied packet; `CLAUDE.md` was not supplied.

1. **The static catalogue needs a distinct preparation route, not just additional descriptors.**

   Descriptor membership only supplies target metadata. Preparation currently enumerates common properties and kernel uniforms; adding descriptors alone does not prepare the new settings. Appending catalogue entries with a null declaration also fails when their properties are absent: `prepareValue` requires a property in that case. Passing them as ordinary uniforms instead adds persistent declarations—the opposite of the plan’s requirement. Existing property ranges can also constrain values unless the catalogue supplies its own domain.  
   Citations: `brush_preparation.cc:175–180, 211–230, 314–325, 360–397`; plan: `25–37`.

   **Minimal correction:** specify a dedicated catalogue pass with native-member addressing, `dynamic=false`, explicit engine-owned validation domains, and no additions to `declarations_`. Preserve owner/type/schema/device-stack validation without reading property getters or using authored property values as the source. Define how a kernel manifest naming a catalogue member is handled: reject a conflicting declaration and prepare each target only once. Otherwise ordinary manifest processing can reintroduce declarations or conflicting domains.

2. **The public command API cannot currently transport the required typed scalar overrides through the shown bindings.**

   `setCommandScalarChecked` exists and supports float/int/bool transport, but `BrushProgram::defineBindings` does not register it. The bound float setters cannot supply exact BOOL or INT32 overrides: program preparation labels all their values FLOAT32, and `prepareValue` rejects type mismatches. Thus binding only the proposed LUT methods still leaves command cavity enable, inversion, curve enable and blur inaccessible through this binding surface.  
   Citations: `brush_program.h:113–115, 151–178`; `brush_program_preparation.cc:18–42, 163–174`; `brush_preparation.cc:193–198`.

   **Minimal correction:** explicitly include a bound checked scalar transport, using a binding-compatible type identifier or typed wrappers, alongside LUT replacement/removal. Require generated-binding coverage for BOOL, signed INT32 and FLOAT32—not merely a successful LUT upload.

3. **LUT inheritance needs an explicit prepared representation and application rule.**

   The plan says an omitted payload inherits the Brush LUT and is copied into the candidate. That must mean copying the original Brush LUT during preflight for **every stage**, including stages without an override. Shared execution reads `brush->cavity_curve` directly. Applying only explicit overrides would let command A’s LUT leak into command B’s omitted payload. Existing stage application and restoration contain only scalar values; the four-byte `Saved` representation cannot carry the LUT.  
   Citations: plan: `38–43`; `brush_preparation.cc:280–297`; `brush_program_preparation.h:41–50`; `brush_executor.h:1045–1051`; `grid_executor.h:1186–1192`.

   **Minimal correction:** give each prepared stage an owned, fully resolved 256-sample LUT; validate inherited samples as well as uploaded samples, including when cavity or curve use is disabled. Apply that LUT at every executing stage and save the original array separately for restoration. Define removal as “resume inheritance on the next preparation,” distinct from installing an identity LUT. Revalidate during execution preparation because `BrushProgram::commands` is public and the Brush entry setter does not check finiteness.  
   Citations: `brush_program.h:73–74`; `brush.h:398–402`.

4. **“Restoration on every exit” must explicitly cover standalone publication.**

   Both standalone prepared executors call `prepared.publish`, which registers declarations, initializes defaults and applies working values, before determining whether the region is nonempty. Neither standalone function installs `ScopedBrushWorkingValues`. Only program execution currently has that guard. Extending the program guard therefore does not satisfy the standalone restoration promise, including successful zero-radius or spatial-miss calls.  
   Citations: `brush_preparation.cc:264–276`; `brush_executor.cc:189–202, 288–290`; `grid_executor.cc:219–237, 295–297`.

   **Minimal correction:** identify the scope protecting the new settings and LUT in all four prepared entry points, installed before their first working-state write. Decide explicitly whether standalone restoration extends to all prepared scalars or only the new executor state. Keep every recoverable scalar/LUT check before publication, topology preparation and counters; restoration of working values cannot undo published declarations.

**Acceptance refinements, separate from blockers:**

- Replace “before allocation” with “before persistent/executor/mesh allocation or mutation.” Read-only preparation already allocates scratch commands, manifests and candidate vectors. A literal no-allocation requirement contradicts the supplied implementation. Citations: plan: `70–73`; `brush_program_preparation.cc:132–159, 201`; `brush_executor.cc:255–257`.

- Make restoration tests use distinct LUTs: Brush=A, command 0=B, command 1=omitted. Assert stage 1 uses A and the Brush ends at A. Add native/property disagreement, absent properties, restrictive property ranges, and duplicate/conflicting manifest targets to test catalogue authority.

- The raw-LUT rejection requirement is already correct, not a newly discovered omission. Pin it to both raw preflights and zero-dab automatic fallback. Current rejection checks enumerate scalar/dynamics overrides and will need the LUT-presence check added. The packet demonstrates the grid zero-dab route; it does not establish all mesh batch or direct raw routes. Citations: `brush_executor.cc:61–94`; `grid_executor.cc:98–136`; `c-api/grid_stroke_c_api.cc:334–347`.

- Separate rejected-command atomicity from accepted empty-call behavior. Existing empty programs clear state and, on grids, increment `stats.dabs`; standalone publication also occurs on misses. Specify which behavior is retained rather than making all counters unchanged an implicit requirement. Citations: `brush_executor.cc:244–253`; `grid_executor.cc:252–263`.

The packet supports the existing all-stage scalar preflight barrier. It does **not** demonstrate an existing late-command scalar publication bug; the correction is to bring catalogue and LUT validation inside that same barrier.