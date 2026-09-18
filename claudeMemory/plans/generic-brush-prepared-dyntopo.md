# Plan 6: prepared dynamic topology

Status: completed on 2026-09-18. [Verified gate](../tests/plan6-dyntopo-gate.json).
Further adversarial reviews were waived by the user.

## Contract and implementation

1. Admit existing prepared kernels on a dyntopo stroke with live topology links.
   Preview and topology mutation remain mutually exclusive. Keep the existing
   command attribute and host-stage capability checks.
2. Add optional topology work to prepared program execution. Validate the whole
   program, frame, topology settings and transaction before any remeshing. Retain
   the prepared command values through remeshing and execution; do not evaluate
   a second time after topology changes.
3. Preserve the host's remesh radius and cadence. An autosmooth command with a
   larger radius broadens deformation and undo support, not the user's detail
   refinement area. Query the evaluated command union after remeshing; never
   retain leaf pointers across topology mutation. Unbounded and anchored stages
   retain their conservative all-leaf deformation policy.
4. Keep topology live, use the existing combined spatial/mesh-log callbacks and
   seal each remeshed dab's topology chunk. First-contact caches already key by
   topology stamp; test actual splits/collapses and reused vertex IDs.
5. Expose an additive checked C API and route supported addon dyntopo programs
   through it. Preserve raw behavior for still-unsupported attributes/host stages;
   generic adoption must eventually refuse silent fallback.

## Gates

- Native: actual topology change, larger later command and radius dynamics,
  cadence skips, nonaccumulation, cavity, symmetry frames, failure before topology
  mutation, exact multi-dab undo/redo, and raw-reference cases with equal settings.
- Installed Blender: require checked calls in background and real headed dyntopo
  gestures; verify topology counts, deformation, cancel/undo and next-stroke state.
- Run existing dyntopo/mesh-log regressions, bindings/typecheck and package smoke.
  Record runtime hashes before marking the task-list deliverable complete.

## Acceptance evidence

All 26 native suites pass. The new C API regression covers actual splits and
collapses, pressure ADD radius growth, an independent larger second command,
off-cadence deformation, nonaccumulation, cavity caches, rejection before mutation
and exact topology/position undo/redo. Integrated execution exactly matches a
separate remesh/deformation reference. Outside-main-radius vertices must move.

Background and headed Blender each pass eight addon lifecycle cases, including
larger DRAW/BSMOOTH commands and invalid typed/settings input, plus four legacy
control runs with exact geometry/topology parity. Four real headed strokes cover
mirror images, remesh cadence, autosmooth, pressure, cavity, accumulation modes,
release/ESC and Blender undo/redo. Ordinary stroke cancellation preserves accepted
dabs and records undo, matching the existing behavior.

Bindings, TypeScript checking, staged source equality and package smoke pass.
The gate records the installed and native DLL hashes. General writable attributes,
other host stages and full generic consumer adoption remain separate Plan 6 work.
