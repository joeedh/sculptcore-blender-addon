param([ValidateSet('numerics', 'integration')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# Fixed source packet for the user-authorized read-only OpenAI plan review.
$reviewFiles = @(
    'AGENTS.md', 'CLAUDE.md',
    'claudeMemory/plans/generic-brush-execution-domains.md',
    'claudeMemory/design/generic-brush-contract-v1.md',
    'engine/source/props/prop_dynamics.h',
    'sculptcore_addon/brush_properties/snapshots.py',
    'sculptcore_addon/brush_properties/commands.py',
    'sculptcore_addon/brush_properties/responses.py',
    'sculptcore_addon/brush_properties/registry.py',
    'sculptcore_addon/brush_properties/adapters.py',
    'sculptcore_addon/stroke_input.py',
    'sculptcore_addon/mapping.py',
    'claudeMemory/scripts/test_checked_brush_bindings.py'
)
$reviewBundle = foreach ($reviewFile in $reviewFiles) {
    'SOURCE FILE: ' + $reviewFile
    $reviewLine = 0
    Get-Content -LiteralPath $reviewFile | ForEach-Object {
        $reviewLine++
        '{0}: {1}' -f $reviewLine, $_
    }
}
$reviewPrompt = @"
Fresh adversarial review of claudeMemory/plans/generic-brush-execution-domains.md.
Your independent lens is $Lens. For numerics, try to kill FLOAT32/FLOAT64 parity,
typed ranges, overflow, interpolation and actual native verification. For integration,
try to kill semantic/native domains, spacing/snake/strength conversion order, the
special projected SIZE boundary, independent owners and the real acceptance gates.
All relevant source follows with line numbers. Use only supplied source. No tools,
commands, edits, builds or delegation. Report concrete blockers and corrections with
citations, or explicitly no blockers. This is the evaluator prerequisite, not full
modal adoption. Do not claim missing out-of-scope integration is a blocker unless
the proposed boundary itself prevents correct subsequent integration. The main
agent is already running the required multiple independent reviews.
"@
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-domains-$Lens-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-domains-$Lens-review.log"
exit $LASTEXITCODE
