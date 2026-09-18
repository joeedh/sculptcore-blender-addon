The supplied implementation closes most preparation seams. I found **one concrete contract mismatch**, but no demonstrated failure of native-value authority, LUT ownership, or scoped restoration. Acceptance evidence is still incomplete; the packet does not establish readiness for sign-off.

**Concrete correction**

1. **Executor-setting manifest validation accepts an omitted range despite requiring an exact catalogue policy.** The catalogue gives every setting a range, including the restricted blur domain. Validation only compares bounds when `entry.hasRange` is true, so a static `INT32 cavity_blur_steps` manifest with no range passes. This contradicts the plan’s exact type/static/range matching requirement. Execution still uses the catalogue domain, so this is a schema-admission defect, not evidence that negative blur reaches execution.  
   **Minimal correction:** require `entry.hasRange == setting.hasRange`, then compare bounds when present. Alternatively, explicitly amend the contract if omission is intended to mean catalogue inheritance.  
   Sources: `brush_preparation.cc:30–39, 363–370, 433–437`; plan `94–100`.

**Implemented protections that survive this review**

- Static values come from native members, independently of property values/getters/ranges; existing property identity/type/schema and static dynamics are checked. Overrides remain subject to the catalogue domain. Sources: `brush_preparation.cc:173–212, 221–256, 433–440`.
- LUT replacement validates before assignment and copies caller storage. Preparation snapshots all 256 samples, including inherited and disabled configurations; each stage reapplies its snapshot. Sources: `brush_program_preparation.cc:114–134`; `brush_preparation.cc:345–352, 308–310`.
- Both executors finish program preparation before selection/execution mutations. Standalone restoration scopes precede publication, and program scopes precede working writes. The destructor restores the LUT and captured native values. Sources: `brush_executor.cc:194–198, 284–298, 342`; `grid_executor.cc:222–225, 285–308`; `brush_program_preparation.cc:277–310`.

**Acceptance gaps and refinements — separate from demonstrated defects**

- **Bindings remain unverified.** Reflection registrations and Python wrappers exist, but the packet omits definitions/exports of `BrushProgram_replaceCavityCurveChecked` and `BrushProgram_removeCavityCurveChecked`, which those wrappers actually call. Generated bindings and installed-package evidence are also absent. Supply those seams and exercise replacement, failed replacement, and inheritance through Python. This is missing evidence, not proof of missing symbols. Sources: `brush_program.h:181–182`; `brush_properties.py:31–49`; plan `42–44, 85–87`.

- **Raw fallback coverage is partial.** Both raw preflight methods reject command LUT payloads, and the supplied grid zero-dab dispatcher invokes that preflight. The packet does not show mesh batch dispatch or nonzero raw program entry points invoking it. Verify rejection before mutation for explicit raw and automatic fallback, with both zero and nonzero dab counts. Sources: `brush_executor.cc:74–78`; `grid_executor.cc:115–118`; `grid_stroke_c_api.cc:334–356`.

- **Restoration tests need actual override execution.** Candidate tests distinguish inherited and explicit LUTs, but execution tests never run a valid command LUT replacement. They check only two restored settings and the context flag. Execute override → inheritance stages with different LUTs and all nine settings; compare resulting stage behavior and exact post-call brush state. Include accepted misses, zero radius, standalone execution, and subsequent raw execution. Sources: `prepared_cavity_cases.h:45–78, 94–100, 152–162`.

- **Late-rejection atomicity assertions are too narrow.** The malformed-later-command test checks evaluation count and the context flag, despite claiming rejection before topology work. Snapshot declarations, named-store presence, settings/LUT, topology state, attributes, undo state, and relevant counters. Also exercise failure through the batch overlay and verify earlier accepted dabs remain committed. Sources: `prepared_cavity_cases.h:158–162`; `dab_inputs.h:20–77`; `grid_stroke_c_api.cc:359–377`.

Cache identity, geometry, and lifetime are left to the other review lens.