param([ValidateSet('lifetime', 'footprint')] [string] $Lens, [switch] $Implementation,
      [string] $Revision = '')
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'claudeMemory/plans/generic-brush-mask-finer-undo.md' },
    @{ Path = 'engine/source/subdiv/grid_stroke_log.h' },
    @{ Path = 'engine/source/subdiv/grid_stroke_log.cc' },
    @{ Path = 'engine/source/subdiv/grid_domain.cc'; Start = 257; End = 348 },
    @{ Path = 'engine/source/subdiv/grids.h'; Start = 155; End = 520 },
    @{ Path = 'engine/source/subdiv/grids.cc'; Start = 334; End = 470 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 88; End = 176 },
    @{ Path = 'engine/source/subdiv/grids.cc'; Start = 1; End = 150 },
    @{ Path = 'engine/tests/test_brush_prepared_execution.cc'; Start = 1400; End = 1770 },
    @{ Path = 'engine/source/subdiv/multires.cc'; Start = 40; End = 96 },
    @{ Path = 'engine/source/subdiv/multires.cc'; Start = 2028; End = 2043 }
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
Fresh adversarial review of the finer-level mask undo implementation plan.
The current packet includes its implementation. Review actual code as well as the
plan; report concrete defects and missing acceptance coverage. Do not assume tests pass.
Your lens is ${Lens}: lifetime covers owning state swaps, channel/level identities,
allocation absence, debt and cached domain lifetime; footprint covers affected-grid
coverage, delta propagation, dedup complexity, honest undo bytes and test gates.
Kill the plan against supplied source, reporting concrete blockers with minimal
corrections and citations. Distinguish acceptance refinements from blockers.
Use only this source packet. No tools, commands, edits, builds or delegation.
Another independent reviewer handles the other lens. This is an authorized review.
"@
$reviewSuffix = if ($Implementation) { 'implementation' } else { 'review' }
$reviewSuffix += $Revision
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-mask-undo-$Lens-$reviewSuffix.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-mask-undo-$Lens-$reviewSuffix.log"
exit $LASTEXITCODE
