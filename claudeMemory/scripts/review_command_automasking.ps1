param([ValidateSet('preparation', 'cache')] [string] $Lens, [switch] $Implementation)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'claudeMemory/plans/generic-brush-command-automasking.md' },
    @{ Path = 'engine/source/brush/brush.h'; Start = 310; End = 521 },
    @{ Path = 'engine/source/brush/brush_preparation.h' },
    @{ Path = 'engine/source/brush/brush_preparation.cc' },
    @{ Path = 'engine/source/brush/brush_program.h'; Start = 1; End = 210 },
    @{ Path = 'engine/source/brush/brush_program_preparation.h' },
    @{ Path = 'engine/source/brush/brush_program_preparation.cc' },
    @{ Path = 'engine/source/brush/prepared_cavity.h' },
    @{ Path = 'engine/tests/prepared_cavity_cases.h' },
    @{ Path = 'engine/python/sculptcore/brush_properties.py'; Start = 1; End = 100 },
    @{ Path = 'engine/source/brush/brush_executor.cc' },
    @{ Path = 'engine/source/brush/grid_executor.cc' },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 1010; End = 1120 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 2330; End = 2395 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 540; End = 600 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 715; End = 760 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1173; End = 1260 },
    @{ Path = 'engine/source/brush/automask.h'; Start = 1; End = 235 },
    @{ Path = 'engine/source/brush/c-api/dab_inputs.h' },
    @{ Path = 'engine/source/brush/c-api/grid_stroke_c_api.cc'; Start = 322; End = 395 }
)
$reviewBundle = foreach ($entry in $reviewFiles) {
    'SOURCE FILE: ' + $entry.Path
    $reviewLine = 0
    Get-Content -LiteralPath $entry.Path | ForEach-Object {
        $reviewLine++
        if (-not $entry.Start -or ($reviewLine -ge $entry.Start -and $reviewLine -le $entry.End)) {
            '{0}: {1}' -f $reviewLine, $_
        }
    }
}
$reviewPrompt = @"
Fresh adversarial review of the command automasking implementation plan. Lens:
${Lens}. Preparation covers authoritative native settings, static scalar catalogue,
command/LUT overrides, publication atomicity, restoration, raw fallback and bindings.
Cache covers configuration identity, first-contact geometry, topology preparation,
stale lifetime, independent command effects, cost and acceptance oracles.
Kill the plan against actual supplied source. Report concrete blockers and minimal
corrections with citations, separating acceptance refinements. This is pre-implementation.
Use only the source packet. No tools, commands, edits, builds or delegation.
Another fresh reviewer handles the other lens. This is an authorized read-only review.
"@
if ($Implementation) {
    $reviewPrompt += "`nThis packet now includes the implementation. Review actual correctness and acceptance gaps; do not treat implemented seams as merely proposed."
}
$reviewSuffix = if ($Implementation) { 'implementation' } else { 'review' }
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-automask-$Lens-$reviewSuffix.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-automask-$Lens-$reviewSuffix.log"
exit $LASTEXITCODE
