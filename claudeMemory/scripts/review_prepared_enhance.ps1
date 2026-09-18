param([ValidateSet('semantics', 'integration')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    'claudeMemory/plans/generic-brush-prepared-enhance.md',
    'engine/source/brush/enhance.h',
    'engine/source/brush/brush_hooks.h',
    'engine/source/brush/brush_hooks.cc',
    'engine/source/brush/brush_preparation.h',
    'engine/source/brush/brush_preparation.cc',
    'engine/source/brush/brush_program_preparation.cc',
    'engine/source/brush/brush_executor.cc',
    'engine/source/brush/brush_executor.h',
    'engine/source/brush/grid_executor.cc',
    'engine/source/brush/grid_attr_bind.h',
    'engine/source/brush/prepared_cavity.h',
    'engine/source/brush/brush.h',
    'engine/source/brush/kernels/enhance.sbrush',
    'engine/tests/prepared_cavity_cases.h',
    'sculptcore_addon/stroke.py',
    'sculptcore_addon/stroke_math.py'
)
$packet = foreach ($path in $reviewFiles) {
    'SOURCE FILE: ' + $path
    $line = 0
    Get-Content -LiteralPath $path | ForEach-Object { $line++; '{0}: {1}' -f $line, $_ }
}
$prompt = @"
Fresh adversarial pre-implementation review of prepared ENHANCE plan, lens $Lens.
Semantics lens: independent command hooks, first-contact cache identity/support,
normalization, live geometry vs base support, pressure, atomicity and independent
oracles. Integration lens: actual buildability, attribute binding/metadata/lifetime,
transaction ownership, mesh/multires domain fallback, topology state, static native
authority and tests. Kill the plan against supplied code. Report concrete blockers
and minimal corrections with citations, separating optional improvements. Another
fresh reviewer covers the other lens. The preceding unbounded slice is implemented
and finishing package checks; do not re-review its separate numerical design.
No tools, edits, commands, builds or delegation. User authorized these read-only
OpenAI CLI reviews. Do not request permission for routine implementation decisions.
"@
$packet | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-enhance-$Lens-review.md" $prompt `
    *> "claudeMemory/tests/plan6-enhance-$Lens-review.log"
exit $LASTEXITCODE
