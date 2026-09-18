# Generic property consumer audit — 2026-09-18

Audit of current working-tree consumers; remaining read-only CLI reviews are
authorized by the user. This supplements the frozen Plan 1
inventory; it is not evidence that these consumers have been converted.

## Execution consumers still to adopt snapshots

| Boundary | Current source | Required integration seam |
| --- | --- | --- |
| Stroke setup | `stroke.py:825–863` | Native/shadow pressure LUT setup and checked scalar synchronization still operate independently of generic snapshots. Clear or replace each old stack before publishing a new configuration. |
| Common mapping | `mapping.py:379–422` | Native/unified strength, local spacing, per-family extras, falloff and legacy generated uniforms are still direct reads. |
| Per-family extras | `mapping.py:43–82` | Plane offset is direct; PINCH intentionally uses local strength; SNAKEHOOK remaps native factor. These are separate adapter rules. |
| Falloff/overlap | `mapping.py:242–264,421–472` | Hardness is read directly at bake time. Spacing affects overlap and its memo key; semantic dynamics must not accidentally rebake curves per dab. |
| Autosmooth | `stroke.py:937–981` | Existence and strength of the secondary BSMOOTH command are decided from local auto_smooth_factor; dynamics that enable a zero-base value must not be omitted by this branch. |
| Accumulation | `stroke.py:1035–1042` | Local use_accumulate is combined with family/mode rules and frozen original-coordinate behavior. |
| Spacing/dyntopo | `stroke.py:962–979,1145–1148` | Radius/spacing influence emitted points and remesh cadence, before engine execution. Engine-only dynamics cannot update these consumers. |
| Python dabs | `stroke.py:1318–1378` | Smooth evaluates pressure in Python, decomposes strength into passes, then writes dab state. Other dabs use native device stacks. One generic stack must not run through both. |
| Batch dabs | `stroke.py:1431–1479` | Radius is per row, but scalar strength is currently one value per entire batch; input samples are per row. See the constraint below. |
| Preview/anchored | `stroke.py:1025,1107–1125,1579–1617` | Radius and strength have separate frozen-anchor/live-preview paths and kernel-specific drag semantics. |
| Cursor | `cursor.py:61`, `stroke.py:1670–1678` | Circle uses native pixel radius times pressure-only scale. It must display the same evaluated size, including non-multiplicative layers and SCENE mode. |
| Size projection | `stroke.py:1789–1819` | Pixel projection returns object-space length. Fallback reads local world diameter and does not honor SCENE mode. Generic correction must use the selected owner's paired state. |
| Texture projection | `texture.py:741–750` | View texture scale uses starting pixel radius, so effective-owner/SCENE size changes must agree with stroke setup. |
| Legacy uniforms | `engine_props.py:apply/sync_authored` | Existing generated names can overlap between kernels. Resolve stable target-specific IDs and validate current manifest type/dynamics/range before upload. |

### Batch transport constraint

`MeshStroke_dabBatchInputs`, `GridStroke_dabBatchInputs` and their program
variants receive one scalar strength for all dabs in an event. Input samples
vary per row and the engine evaluates native dynamics. Consequently a future
host evaluator cannot simply evaluate strength once using the latest event
and reuse it for every row. Nor can it supply per-dab values through a scalar
parameter without an explicit transport change. Typed native spacing and snake
unit conversion need a deliberate host/engine boundary; clearing every native
stack and reusing today's batch ABI would lose varying device behavior.

The numerical evaluator prerequisite remains useful for spacing, cursor and
smooth decomposition. Its existence alone does not authorize bypassing native
program preflight or claiming batch integration complete.

### Engine program capability constraint

Prepared BSMOOTH, non-accumulating execution, MASK (including finer-level undo),
and command-owned cavity settings now have recorded native/DLL/headed gates.
See [Plan 6 evidence](generic-brush-plan6-evidence.md). Those capabilities no
longer block generic consumer adoption on their own.

Mesh still guards dyntopo, anchored grab, unbounded commands, general attributes
and overrides, host callbacks, unclassified hooks, preview and unsupported
falloff. Grid additionally guards face/original-normal paths, attribute mirrors
and nondefault multires edit/writeback targets. Compiler host/reduce certificates
are being added, but executor admission remains separately gated by support and
numerical validation. Generic host adoption and geometric viewDir symmetry are
still open. Do not use raw fallback to claim generic-stack coverage.

## UI and compatibility consumers

- `vanilla_panels.py` clones native basic, advanced, stroke, falloff, texture,
  color and context panels. Its pressure-row wrapper still delegates the scalar
  write target to native `UnifiedPaintPanel.prop_unified`.
- `ui.py:85–121` still defines the limited duplicate cavity panel. Remove it only
  when the surviving full renderer uses the actual executing SculptCore settings.
- `keymap.py:42,78–90` still routes radial and bracket edits through native paths.
  These need effective-owner edits and paired-size cancel restoration.
- `ops.py:409` invokes radial control for dyntopo detail; preserve its distinct
  Scene-level target rather than treating every radial call as a brush property.
- Generated `Brush.sculptcore` compatibility aliases, raw writes and animation
  overlay remain Plan 8 tasks; retaining the frozen catalogue is not migration.

## Current review dependency

The user approved CLI use for all remaining Plan 6–8 reviews. Both independent
reviews of [the numerical/integration slice](../plans/generic-brush-execution-domains.md)
completed. Their typed-bound corrections are implemented and its
[gate passed](../tests/plan6-domains-gate.json). The consumer seams above remain
unconverted; the evaluator does not by itself complete their integration.
