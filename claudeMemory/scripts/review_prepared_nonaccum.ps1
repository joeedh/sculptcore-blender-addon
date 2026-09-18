param([ValidateSet('mesh', 'grid')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'claudeMemory/plans/generic-brush-prepared-nonaccum.md' },
    @{ Path = 'engine/source/brush/brush_executor.cc' },
    @{ Path = 'engine/source/brush/grid_executor.cc' },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 455; End = 535 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 680; End = 1060 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 635; End = 785 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1040; End = 1310 },
    @{ Path = 'engine/source/brush/accum_mode.h' },
    @{ Path = 'engine/source/brush/brush_preparation.h' },
    @{ Path = 'engine/source/brush/brush_program_preparation.cc'; Start = 118; End = 250 },
    @{ Path = 'engine/tests/test_brush_prepared_execution.cc'; Start = 650; End = 865 }
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
Fresh adversarial read-only review of the prepared-nonaccum implementation plan.
Your lens is ${Lens}: scratch factories, selected accumulation template, original
coordinate/displacement lifetime, preflight atomicity, capture and undo, program
stage mixing, region growth and meaningful acceptance against supplied code.
Try to kill this plan; cite concrete blockers and minimal corrections. Distinguish
acceptance refinements from actual blockers. Do not demand separate gated features
(grab/dyntopo/cavity/attributes) unless this bounded change itself is unsafe.
Use only supplied source packet. No tools, commands, edits, builds or delegation.
Another independent reviewer covers the other executor. Say no blockers if none
are substantiated. This is an authorized review only, not an implementation task.
"@
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-nonaccum-$Lens-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-nonaccum-$Lens-review.log"
exit $LASTEXITCODE
