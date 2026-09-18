# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record the completed Plan 2 gate without changing later plan checkboxes."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "plans/generic-brush-properties-tasks.md"
text = path.read_text(encoding="utf-8")
text = text.replace("Status: Plan 1 complete; Plan 2 in progress.",
                    "Status: Plans 1–2 complete; Plan 3 in progress.")
text = text.replace("| [ ] | [2. Owner-aware", "| [x] | [2. Owner-aware")
start = text.index("## Plan 2: Owner-aware CurveMapping API")
end = text.index("## Plan 3: Typed device dynamics", start)
section = text[start:end].replace("- [ ]", "- [x]")
section = section.replace("Final interactive editor lifecycle cases remain part of the parent gate.",
                          "Interactive lifecycle checks passed; see the final completion evidence.")
section = section.replace("Dialog-driven notifications remain outstanding.",
                          "Dialog-driven actual-owner notifications and asset Revert also passed.")
section += "Completion: 2026-09-16. [Final gate evidence](../codebase/generic-brush-plan2-evidence.md#completion-gate--2026-09-16) records the installed binary, native tests, actual headed interactions, assets and regression matrix.\n\n"
path.write_text(text[:start] + section + text[end:], encoding="utf-8")

path = root / "codebase/generic-brush-plan2-evidence.md"
text = path.read_text(encoding="utf-8").replace(
    "2026-09-15. **Plan 2 is in progress; its completion gate is not passed.**",
    "2026-09-16. **Plan 2 complete.** The chronological notes below retain intermediate limitations; the final completion record supersedes them.")
text += """

## Completion gate — 2026-09-16

Installed Blender SHA256:
`5d444c284ee157403f8c9437b9e98c4ac287e6ba84623781070902433c550224`.
The final source cleanup only removes three duplicate comment headers.

The point-removal failure was a driver error: hiding the selected-point rows
moved Apply upward by 62 pixels. Screenshots before/after Remove showed the
working point actually removed; clicking the old Apply position canceled the
popup. The corrected driver passed insertion, Vector handle and removal, each
with exactly one commit callback. No production guard was weakened.

Both graph insertion paths reject 32767-point curves without a revision or
callback change. In the actual headed process, raw construction/sync took:

| Points | Raw construction | Explicit sync |
| --- | --- | --- |
| 2048 | 0.00220 s | 0.00339 s |
| 8192 | 0.01346 s | 0.01258 s |
| 32767 | 0.06445 s | 0.04822 s |

Evidence: `tests/owned-curve-editor-array/controls.jsonl`, screenshots and
`test.json`. The JSON labels this individual session partial because earlier
sessions cover the rest of the editor matrix. Combined recorded sessions cover
the complete Plan 2 gate; no single session is claimed to cover every case.

Final installed-binary regressions all passed:

| Coverage | Evidence under tests/ |
| --- | --- |
| 25-case RNA lifecycle and fresh file read | owned-curve-final-rna.log, owned-curve-final-rna-read.log |
| 13 cache API cases | owned-curve-final-cache.log |
| 3 copy/override policy cases | owned-curve-final-copy.log |
| Owned external asset Save/Revert and fresh read | owned-curve-final-assets.log, owned-curve-final-assets-read.log |
| Stock/prior-fork preserved fixtures materialized through real API | owned-curve-final-old-readers.log |
| 16 native curve notification cases and fresh asset read | owned-curve-final-native.log, owned-curve-final-native-read.log |
| Headed RNA/cache undo/redo and template | owned-curve-final-headed.log |
| Headed ESC and window-close stroke cancellation | owned-curve-final-stroke-cancel.log |
| Eight frozen geometry cases, bit exact | owned-curve-final-geometry.log |

The headed logs contain no traceback or failed assertion; stderr records the
existing sandbox denial reading Blender's user recents.toml. Native codec/runtime
results (6 + 14), actual GUI Save/Revert (.375/.75/.375), transaction lifecycle,
multi-window rejection and generated RST API documentation are recorded above.
Library overrides are explicitly read-only in v1; rejected edits preserve data.
Old-reader compatibility is limited to the actual tested binaries/payloads.

Plan 3 remains open. Engine typed evaluation is being implemented separately;
Plan 2 completion does not advertise migrated addon properties or device inputs.
"""
path.write_text(text, encoding="utf-8")

path = root / "README.md"
text = path.read_text(encoding="utf-8").replace("preservation tests, build evidence and outstanding API gate.",
                                "preservation tests and completed native/API/editor gate.")
text = text.replace("RNA undo/redo passed. The editor gate remains open.",
                    "RNA undo/redo and actual editor gates passed.")
text = text.replace("initialization and revision-bound transactions; dialog integration in progress.",
                    "initialization and revision-bound transactions; headed lifecycle gate passed.")
text = text.replace("— proposed first Plan 3 engine slice; numeric and integration reviews underway.",
                    "— reviewed first Plan 3 engine slice; implementation and native checks in progress.")
path.write_text(text, encoding="utf-8")
