# Brush device input delivery

Plan 3 completed on 2026-09-17. See the completion gate in
generic-brush-plan3-evidence.md for exact binaries and test results.

## Blender events

`Event.time` is a readonly Python double in seconds on the RNA-backed Event.
`has_time` distinguishes acquisition timestamps from unavailable timestamps;
zero is a valid timestamp. `is_input_sample` distinguishes actual input from
internally generated mouse moves. `has_pressure`, `has_tilt_x` and `has_tilt_y`
are independent. Mouse pressure is defined as one; absent tablet channels do
not synthesize zero values. Windows mouse, Pointer and Wintab producers are
audited. Other backends conservatively leave acquisition time and tablet-channel
availability unset pending producer-specific validation. Known Cocoa/Wayland
cursor warps are marked synthetic.

`Window.event_simulate_input` takes the existing `event_simulate` arguments plus
optional `time`, `tablet`, `pressure`, `tilt_x` and `tilt_y`. Omission or None
means unavailable. Tablet axes require `tablet=True`; pressure is [0,1] and tilt
is [-1,1]. Invalid/nonfinite extension values reject before queue mutation.
The new entry retires a preceding mouse move using the same helper as native
input, preserving timestamp/channel metadata through INBETWEEN conversion.
The original simulator remains available and clears acquisition metadata.

## Sampling

`stroke_input.InputSampler` produces immutable samples. Tilt normalizes to
[0,1]. Speed is screen distance divided by acquisition-time interval and the
positive Scene `sculptcore_speed_reference` (default 1000 pixels/second), clamped
to [0,1]. A valid first sample has speed zero; unavailable/nonincreasing time
resets the derivative anchor. Generated moves leave history untouched.

The actual modal `StrokeSpacer` associates each knot with its sample. Each
emitted dab interpolates pressure/tilt/time using traveled arc fraction within
its source segment, with that segment's speed. An absent endpoint channel stays
absent for the segment. Lookahead never substitutes the newest event's sample.
Release feeds the final real event then flushes the remaining segment once.
Grab and preview consume real INBETWEEN inputs too: a generated trailing move
must not suppress the last real deformation.

Symmetry reflects centers/normals while reusing the same device sample. Every
logical dab clears previous channels, regardless of pressure toggles. Batch
raycasts compact sample rows using the same hit indexes as geometry rows.

## Engine execution

Additive `MeshStroke_*Resolved` and `GridStroke_*Resolved` entries expose the
prepared standalone/program executors. `*dabBatchInputs` and
`*dabBatchProgramInputs` accept seven-float geometry rows and six-float input
rows: pressure, tilt X, tilt Y, speed, exact presence mask (0–15), invert (0/1).
Counts refer to complete caller-owned rows; all buffers are validated before
the first write. The last policy argument is 0 for legacy raw source semantics,
1 for required prepared execution, or 2 for capability selection before execution.
No failed execution retries under another policy. A failed later dab preserves
earlier successful geometry in the open undo transaction and returns -1.

Prepared execution owns evaluated-radius region selection and typed working
values. Bounded spherical execution supports finite zero-edge falloff LUTs;
nonzero-edge curves remain on the explicit raw path. Unsupported host stages,
hooks, attributes, cavity caches, anchored/preview and topology modes are not
silently treated as prepared-capable. Raw standalone execution validates all
configured numeric stacks on every call and rejects noncommon dynamics it
cannot consume. Raw programs keep their existing authored-uniform source
policy. Independent command configurations remain Plan 6.

Python `set_command_scalar` provides checked float/int/bool command overrides,
including integers above 2^24 without float32 transport. `engine_props` hands
mapped dynamic uniforms into authored storage once per stroke; static settings
continue to read authoritative native fields/typed slots. Per-dab writes touch
radius, strength and inversion, without republishing other evaluated caches.

## Test interpretation

The pure tests import the actual modal spacer AST. The headed harness drives
the real operator with changing pressure, independent tilt availability and
timestamps. It compares all emitted samples across mesh/grid, Python/batch and
queued/delayed delivery, and verifies deformation in every case. Public native
typed geometry tests use prescribed hits to compare execution grouping.
Prebatch raycasts can observe a different surface from sequential evolving
raycasts; no general geometry equivalence is claimed for that separate algorithm.
