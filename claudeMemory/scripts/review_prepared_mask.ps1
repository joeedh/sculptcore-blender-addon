param([ValidateSet('admission', 'storage')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'claudeMemory/plans/generic-brush-prepared-mask.md' },
    @{ Path = 'engine/source/brush/grid_executor.cc' },
    @{ Path = 'engine/source/brush/brush_executor.cc' },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 88; End = 176 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 718; End = 785 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1040; End = 1140 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1220; End = 1320 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1536; End = 1570 },
    @{ Path = 'engine/source/subdiv/grid_domain.cc'; Start = 257; End = 348 },
    @{ Path = 'engine/source/subdiv/grid_stroke_log.cc'; Start = 1; End = 251 },
    @{ Path = 'engine/source/subdiv/grids.h'; Start = 256; End = 357 },
    @{ Path = 'engine/source/brush/kernels/mask.sbrush' },
    @{ Path = 'engine/source/brush/brush_program_preparation.cc'; Start = 118; End = 250 },
    @{ Path = 'engine/tests/test_brush_prepared_execution.cc'; Start = 250; End = 380 }
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
Fresh independent adversarial review of the prepared-mask implementation plan.
Your lens is ${Lens}. Admission: capability scope, complete preflight, malformed
existing mask channels, atomic failed/missed/zero dabs and real route evidence.
Storage: lazy channel timing, mask/position/store capture, undo/redo, mixed programs,
first-miss and first-nonmask dabs, geometry-independent mask scoring.
Try to kill the plan against supplied source; cite concrete blockers and minimal
corrections. Distinguish actual blockers from acceptance refinements. Do not
demand separately gated attributes/cavity/face/layer/host integration unless this
bounded change itself is unsafe. No tools, commands, edits, builds or delegation.
Use only this packet. Another fresh reviewer handles the other lens.
"@
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-mask-$Lens-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-mask-$Lens-review.log"
exit $LASTEXITCODE
