param([ValidateSet('compiler', 'execution')] [string] $Lens, [switch] $Implementation)
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
$reviewFiles = @(
    @{ Path = 'claudeMemory/plans/generic-brush-prepared-unbounded.md' },
    @{ Path = 'engine/source/brush/compiler/ir.h' },
    @{ Path = 'engine/source/brush/compiler/prepared_preludes.h' },
    @{ Path = 'engine/source/brush/prepared_cavity.h' },
    @{ Path = 'engine/tests/prepared_unbounded_cases.h' },
    @{ Path = 'claudeMemory/plans/generic-brush-kelvinlet-numerics.md' },
    @{ Path = 'engine/source/props/prop_declarations.cc'; Start = 20; End = 108 },
    @{ Path = 'engine/tests/test_sbrush_member_types.cc' },
    @{ Path = 'engine/source/brush/compiler/emit_cpp.cc'; Start = 150; End = 325 },
    @{ Path = 'engine/source/brush/compiler/emit_cpp.cc'; Start = 765; End = 825 },
    @{ Path = 'engine/source/brush/compiler/emit_cpp.cc'; Start = 1020; End = 1150 },
    @{ Path = 'engine/source/brush/compiler/emit_cpp.cc'; Start = 1420; End = 1505 },
    @{ Path = 'engine/source/brush/compiler/emit_cpp.cc'; Start = 2180; End = 2475 },
    @{ Path = 'engine/source/brush/brush_preparation.h' },
    @{ Path = 'engine/source/brush/brush_preparation.cc' },
    @{ Path = 'engine/source/brush/brush_program_preparation.cc' },
    @{ Path = 'engine/source/brush/brush_executor.cc' },
    @{ Path = 'engine/source/brush/grid_executor.cc' },
    @{ Path = 'engine/source/brush/brush_command.h'; Start = 350; End = 375 },
    @{ Path = 'engine/source/brush/brush_command.h'; Start = 470; End = 525 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 520; End = 665 },
    @{ Path = 'engine/source/brush/brush_executor.h'; Start = 1035; End = 1080 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1050; End = 1140 },
    @{ Path = 'engine/source/brush/grid_executor.h'; Start = 1180; End = 1230 },
    @{ Path = 'engine/source/brush/kernels/kelvinlet.sbrush' },
    @{ Path = 'engine/source/brush/kernels/generated/kelvinlet.brush.gen.h' },
    @{ Path = 'engine/source/brush/c-api/mesh_stroke_batch_c_api.cc'; Start = 120; End = 250 },
    @{ Path = 'engine/source/brush/c-api/grid_stroke_c_api.cc'; Start = 290; End = 395 },
    @{ Path = 'engine/source/mesh/attribute.h'; Start = 240; End = 275 }
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
Fresh adversarial review of the proposed prepared-unbounded implementation plan.
Lens: ${Lens}. Compiler lens: buildability and soundness of no-op host clamp and
pure scalar reduce proofs, range normalization, emitter state, hidden side effects,
generated factory eligibility and backward compatibility. Execution lens: snapshots,
unbounded support, independent commands, cutoff/no-cutoff, cavity contact, state
restoration, atomic failure, C API/batches, lifetimes and acceptance oracles.
Kill this plan against supplied code. Report concrete blockers with citations and
minimal corrections, separating optional refinements. Another fresh reviewer handles
the other lens. Use only the packet. No tools, edits, commands, builds or delegation.
This is an authorized read-only pre-implementation review; no code for this slice
has been changed yet. Do not require user confirmation for routine corrections.
"@
if ($Implementation) {
    $reviewPrompt = @"
Fresh adversarial source review of compiler prelude certificate implementation.
Read prepared_preludes.h, its emitter integration and tests. Find unsound eligibility,
initialization/shadowing mistakes, float emitted semantics mismatches, or regressions.
The unbounded executor guard is deliberately still enabled pending the separate
numerical/execution obligation; do not report that known staged limitation as a bug.
Certificates guarantee shared-state/initialization only, not arbitrary finite math.
Report concrete issues and fixes with source citations. Use only the supplied packet.
No tools, edits, builds, commands or delegation. Read-only review authorized by user.
"@
    if ($Lens -eq 'execution') {
        $reviewPrompt = @"
Fresh adversarial source review of the prepared-unbounded implementation.
Review actual snapshots, native scopes, vector/cutoff validation before mutation,
standalone/program/validateOnly behavior, all-leaf query, cavity first contact,
host certification gating, lifetime constraints and tests. Find concrete defects
or missing acceptance cases with minimal corrections and citations. Anchored grabs
remain deliberately excluded. Another reviewer covers Kelvinlet arithmetic itself.
Use only the packet. No tools, edits, commands, builds or delegation. User authorized
this read-only review; do not ask for approval of routine corrections.
"@
    }
}
$reviewSuffix = if ($Implementation) { '-implementation' } else { '' }
$reviewBundle | & 'C:/Users/joeed/AppData/Local/OpenAI/Codex/bin/12219cbfbcbddde7/codex.exe' exec `
    --ignore-user-config --ephemeral --sandbox read-only --color never `
    -C 'C:/dev/blender/sculptcore-blender-addon' `
    -o "claudeMemory/tests/plan6-unbounded-$Lens$reviewSuffix-review.md" $reviewPrompt `
    *> "claudeMemory/tests/plan6-unbounded-$Lens$reviewSuffix-review.log"
exit $LASTEXITCODE
