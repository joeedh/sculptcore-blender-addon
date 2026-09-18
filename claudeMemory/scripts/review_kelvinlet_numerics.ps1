param([ValidateSet('numerical', 'compatibility')] [string] $Lens, [switch] $Implementation,
      [switch] $Followup)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    'claudeMemory/plans/generic-brush-kelvinlet-numerics.md',
    'engine/source/brush/kernels/kelvinlet.sbrush',
    'engine/source/brush/kernels/generated/kelvinlet.brush.gen.h',
    'engine/source/brush/brush_preparation.cc',
    'engine/source/brush/brush_program_preparation.cc',
    'engine/source/brush/brush_command.h',
    'engine/source/brush/compiler/prepared_preludes.h',
    'engine/source/brush/kernels/ir/intrinsics.cc'
    'engine/tests/prepared_unbounded_cases.h'
)
$reviewBundle = foreach ($path in $reviewFiles) {
    'SOURCE FILE: ' + $path
    $reviewLine = 0
    Get-Content -LiteralPath $path | ForEach-Object { $reviewLine++; '{0}: {1}' -f $reviewLine, $_ }
}
$reviewPrompt = @"
Fresh adversarial review of proposed Kelvinlet numerical correction, lens $Lens.
Numerical lens: algebraic equivalence, intermediate bounds, underflow, cancellation,
origin, finite scalar radius/material endpoints, independent reference test design.
Compatibility lens: DSL/backend buildability, raw/prepared behavior, cutoff order,
state/property contract, tests needed before admission. Kill the plan against code.
Separate concrete blockers from optional refinements and existing engine limits.
Suggest minimal corrections. Another independent reviewer covers the other lens.
Only supplied packet; no tools, edits, commands, builds or delegation. User authorized
these read-only OpenAI CLI reviews. Do not ask for confirmation of routine fixes.
"@
if ($Implementation) {
    $reviewPrompt = @"
Fresh adversarial review of actual Kelvinlet numerical correction and native tests.
The plan includes the prior review dispositions. Check actual DSL code, native
cutoff, original-formula double oracle, accuracy scope, edge cases and remaining
intermediate overflow/underflow. Report concrete bugs and minimal fixes. A separate
reviewer handles prepared executor integration. Only supplied packet; no tools,
edits, commands, builds or delegation. Read-only review authorized by user.
"@
}
$reviewSuffix = if ($Implementation) { '-implementation' } else { '' }
if ($Followup) { $reviewSuffix += '-followup' }
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-kelvinlet-$Lens$reviewSuffix-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-kelvinlet-$Lens$reviewSuffix-review.log"
exit $LASTEXITCODE
