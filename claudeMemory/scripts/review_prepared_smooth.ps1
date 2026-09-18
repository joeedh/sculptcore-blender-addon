param([ValidateSet('mesh', 'grid')] [string] $Lens)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'CLAUDE.md'; Start = 324; End = 350 },
    @{ Path = 'engine/CLAUDE.md'; Start = 609; End = 645 },
    @{ Path = 'claudeMemory/plans/generic-brush-prepared-boundary-smooth.md' },
    @{ Path = 'engine/source/brush/brush_hooks.h' },
    @{ Path = 'engine/source/brush/brush_hooks.cc' },
    @{ Path = 'engine/source/brush/brush_executor.cc' },
    @{ Path = 'engine/source/brush/grid_executor.cc' },
    @{ Path = 'engine/source/brush/grid_attr_bind.h'; Start = 85; End = 153 },
    @{ Path = 'engine/source/brush/brush_command.h'; Start = 22; End = 96 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 630; End = 866 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 1300; End = 1320 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 1690; End = 1818 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 1833; End = 1945 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 660; End = 725 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1068; End = 1140 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1374; End = 1455 },
    @{ Path = 'engine/source/brush/brush_program_preparation.cc'; Start = 118; End = 250 },
    @{ Path = 'engine/tests/test_brush_prepared_execution.cc'; Start = 563; End = 855 }
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
Fresh read-only adversarial review of the prepared-boundary-smooth implementation
plan in this source packet. Your lens is $Lens. Mesh: hook classification, preflight,
boundary/topology lifetime, single vs program entrypoints and undo. Grid: attribute
type/domain safety, DefaultColumn routing, no channel/mirror writes, scope of native
and actual headed acceptance gates. Try to kill the plan against supplied actual
source; report concrete blockers with line citations and minimal corrections.
Use only this packet. No tools, commands, edits, builds or delegation. Another
independent reviewer covers the other lens. Do not demand deferred general host
hooks/attributes/cavity integration unless the proposed boundary itself is unsafe.
Do not infer approval from code comments; this is a review only. Say no blockers
if none are substantiated, and distinguish acceptance refinements from blockers.
"@
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-bsmooth-$Lens-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-bsmooth-$Lens-review.log"
exit $LASTEXITCODE
