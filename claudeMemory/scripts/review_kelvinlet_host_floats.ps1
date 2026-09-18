param([ValidateSet('contract', 'compatibility')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    'claudeMemory/plans/generic-brush-kelvinlet-numerics.md',
    'claudeMemory/plans/generic-brush-prepared-unbounded.md',
    'claudeMemory/tests/plan6-kelvinlet-denormal-probe.json',
    'claudeMemory/scripts/probe_plan6_kelvinlet_denormals.py',
    'engine/source/brush/kernels/kelvinlet.sbrush',
    'engine/source/brush/brush_preparation.cc',
    'engine/source/brush/c-api/dab_inputs.h',
    'engine/source/brush/brush.cc',
    'engine/python/sculptcore/brush_properties.py',
    'engine/tests/prepared_unbounded_cases.h'
)
$reviewBundle = foreach ($path in $reviewFiles) {
    'SOURCE FILE: ' + $path
    $line = 0
    Get-Content -LiteralPath $path | ForEach-Object { $line++; '{0}: {1}' -f $line, $_ }
}
$reviewPrompt = @"
Fresh read-only adversarial review, lens $Lens. Decide the smallest sound disposition
of the host denormal finding in the numerical plan. Blender flushes binary32
subnormals during Python/reflection conversion before native execution; native IEEE
tests pass them. Proposed compatibility disposition: preserve the caller's floating
environment and existing transport semantics, document host subnormal limits,
test actual delivered zero versus intact normal radius separately, and test the
native field down to the true IEEE accepted minimum. Do not claim a nonzero input
executed if transport already made it zero. Is that sufficient within this scoped
Kelvinlet correction, or is checked double-based property transport/preflight
silently corrupting a newly promised value contract? Identify actual reachable
failures and a minimal alternative if needed. Do not propose global FTZ changes
or broad unrelated FPU refactoring. No tools, edits, commands, builds or delegation.
The user authorized read-only OpenAI CLI reviews. Another fresh review uses the
other lens. Output actionable findings with source references, not speculative
scope expansion. Distinguish a failed test assumption from a kernel bug.
"@
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-kelvinlet-host-$Lens-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-kelvinlet-host-$Lens-review.log"
exit $LASTEXITCODE
