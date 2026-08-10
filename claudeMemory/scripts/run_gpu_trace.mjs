// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

// A/B GPU trace: the same synthesized sculpt stroke, captured with RenderDoc in
// native Blender sculpt mode and in SculptCore's, then reduced to one table.
//
//   node claudeMemory/scripts/run_gpu_trace.mjs \
//        --blender C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe \
//        [--grid 64] [--level 4] [--frames 12] [--engines native,sculptcore]
//        [--backend opengl] [--out DIR]
//
// Each arm runs under `renderdoccmd capture`, which injects renderdoc.dll before
// Blender starts; bench_multires_sc.py then drives the capture from inside the
// process (see gpu_trace.py) so the traced frames are the sculpt frames and not
// whatever happened to be on screen when a hotkey was pressed.
//
// Both arms are pinned to `--gpu-backend opengl --gpu-vsync off`. vsync off
// because a 16.7 ms cap would flatten exactly the differences being looked for
// (the existing bench notes the same trap for idle_frame_ms).
//
// OpenGL, not Vulkan, and not by preference: **RenderDoc cannot capture this
// Blender under Vulkan at all.** Its Vulkan capture layer does not support
// `VK_KHR_buffer_device_address`, so it filters the feature out of the device it
// presents; Blender's Vulkan backend requires it and rejects every device:
//
//     WARNING Device [...] does not meet minimum requirements.
//             Missing features are [buffer device address]
//     ERROR   No Vulkan device found that meets the minimum requirements.
//
// Blender then silently falls back to OpenGL, so a run that *asks* for Vulkan
// under capture produces GL captures wearing a Vulkan label. Verified against
// RenderDoc 1.45: `--debug-gpu` alone keeps the Vulkan backend, and only adding
// the capture layer triggers the fallback -- the layer is the cause, not the
// flag. Asking for GL up front makes both arms deterministic and identical.
//
// It also removes the need for `--debug-gpu`, which under Vulkan would be
// mandatory: `vk_restrict_loader_layers()` (vk_backend.cc) sets
// `VK_LOADER_LAYERS_DISABLE=~implicit~` and re-allows `VK_LAYER_RENDERDOC_*`
// only when `G_DEBUG_GPU` is set, so without it the layer is disabled and every
// capture call is a silent no-op. That flag is not free -- it also suppresses
// the Vulkan pipeline cache -- and on the GL path none of it applies: RenderDoc
// hooks `opengl32` directly, with no loader layer and no env var involved.
//
// A note on what this measures. The add-on selects no compute backend and the
// engine defaults to BrushBackend::Cpp, so SculptCore's sculpting is CPU-side
// today: these captures are a *draw path* A/B -- the external draw provider
// against Blender's PBVH draw -- not a comparison of sculpt kernels. Wall-clock
// numbers in the same JSON (cycle_ms, sculpt_phase_ms) remain the headline
// figures, and they are inflated for both arms by the capture hook.

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const BENCH = path.join(HERE, "bench_multires_sc.py");
const ANALYZE = path.join(HERE, "analyze_gpu_trace.py");

function parseArgs() {
  const out = {
    blender: "C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe",
    renderdoc: "C:/Program Files/RenderDoc",
    grid: 64,
    level: 4,
    frames: 12,
    strokes: 8,
    strokeSteps: 20,
    traceAfter: 3,
    mode: "multires",
    backend: "opengl",
    engines: "native,sculptcore",
    out: path.join(HERE, "gpu-trace-results"),
    timeout: 1800,
  };
  const argv = process.argv.slice(2);
  const numeric = new Set(["grid", "level", "frames", "strokes", "strokeSteps", "traceAfter", "timeout"]);
  const alias = { "stroke-steps": "strokeSteps", "trace-after": "traceAfter" };
  for (let i = 0; i < argv.length; i++) {
    const raw = argv[i].replace(/^--/, "");
    const key = alias[raw] || raw;
    if (!(key in out)) throw new Error(`unknown argument: ${argv[i]}`);
    out[key] = numeric.has(key) ? Number(argv[++i]) : argv[++i];
  }
  return out;
}

const args = parseArgs();
// Absolute: every path here is handed to a child whose cwd is the Blender
// install dir (renderdoccmd -d), so a relative --out would be written there and
// then looked for here.
args.out = path.resolve(args.out);
args.blender = path.resolve(args.blender);
mkdirSync(args.out, { recursive: true });

if (args.backend === "vulkan") {
  // Not blocked -- a future RenderDoc may support buffer_device_address -- but
  // the failure mode is silent (GL captures under a Vulkan request), so say so.
  process.stdout.write(
    "!! --backend vulkan: RenderDoc's Vulkan layer strips buffer_device_address, which\n" +
    "   Blender requires, so Blender will fall back to OpenGL and capture GL instead.\n" +
    "   Check the reported api= column against what you asked for.\n");
}

const renderdoccmd = path.join(args.renderdoc, "renderdoccmd.exe");
const qrenderdoc = path.join(args.renderdoc, "qrenderdoc.exe");
for (const [label, exe] of [["blender", args.blender], ["renderdoccmd", renderdoccmd], ["qrenderdoc", qrenderdoc]]) {
  if (!existsSync(exe)) throw new Error(`${label} not found at ${exe}`);
}

// --- capture ---------------------------------------------------------------

function runArm(engine) {
  const jsonPath = path.join(args.out, `${engine}.json`);
  const captureDir = path.join(args.out, "captures");
  const blenderArgs = [
    "--factory-startup", "--enable-event-simulate", "--no-window-focus",
    "-p", "0", "0", "1280", "800",
    "--gpu-backend", args.backend, "--gpu-vsync", "off",
    "--python-exit-code", "1", "--python", BENCH, "--",
    "--out", jsonPath, "--label", engine, "--engine", engine,
    "--grid", String(args.grid), "--level", String(args.level), "--mode", args.mode,
    "--strokes", String(args.strokes), "--stroke-steps", String(args.strokeSteps),
    "--paced-stroke",
    "--gpu-trace", String(args.frames),
    "--trace-after-strokes", String(args.traceAfter),
    "--capture-dir", captureDir,
  ];

  // -w so this returns only once Blender is gone and every .rdc is closed.
  const captureArgs = ["capture", "-w", "-d", path.dirname(args.blender), args.blender, ...blenderArgs];

  process.stdout.write(`\n=== ${engine} :: capturing ${args.frames} frames\n`);
  const proc = spawnSync(renderdoccmd, captureArgs, { encoding: "utf8", timeout: args.timeout * 1000 });
  for (const line of (proc.stdout || "").split("\n")) {
    if (/\[bench\]|BENCH|Error|Traceback|WARNING/.test(line)) process.stdout.write(`    ${line.trim()}\n`);
  }
  if (!existsSync(jsonPath)) {
    process.stdout.write(`    !! no result written (exit ${proc.status})\n`);
    if (proc.stderr) process.stdout.write(`    ${proc.stderr.split("\n").slice(-5).join("\n    ")}\n`);
    return null;
  }
  const result = JSON.parse(readFileSync(jsonPath, "utf8"));
  const captures = result.captures || [];
  process.stdout.write(`    ${captures.length} captures, cycle_ms median ${(result.cycle_ms?.median ?? NaN).toFixed(2)}\n`);
  if (result.error) process.stdout.write(`    ERROR: ${String(result.error).split("\n").slice(-3).join(" ")}\n`);
  return result;
}

const engines = args.engines.split(",").map((e) => e.trim()).filter(Boolean);
const runs = new Map();
for (const engine of engines) {
  const result = runArm(engine);
  if (result) runs.set(engine, result);
}

if (!runs.size) {
  process.stdout.write("\nNo arm produced a result; nothing to analyse.\n");
  process.exit(1);
}

// --- replay analysis -------------------------------------------------------

const job = { out: path.join(args.out, "gpu_stats.json"), captures: [] };
for (const [engine, result] of runs) {
  for (const entry of result.captures || []) job.captures.push({ label: engine, path: entry.path });
}

let stats = { captures: [] };
if (job.captures.length) {
  const jobPath = path.join(args.out, "analyze_job.json");
  writeFileSync(jobPath, JSON.stringify(job, null, 2));
  process.stdout.write(`\n=== analysing ${job.captures.length} captures via qrenderdoc\n`);
  // qrenderdoc is a GUI binary: its stdout goes nowhere and the job travels by
  // environment variable, because its embedded exec defines no __file__.
  const proc = spawnSync(qrenderdoc, ["--python", ANALYZE], {
    encoding: "utf8",
    timeout: args.timeout * 1000,
    env: { ...process.env, SC_GPU_TRACE_JOB: jobPath },
  });
  if (existsSync(job.out)) {
    stats = JSON.parse(readFileSync(job.out, "utf8"));
  } else {
    process.stdout.write(`    !! analysis wrote nothing (exit ${proc.status})\n`);
    if (existsSync(jobPath + ".error.txt")) {
      process.stdout.write(readFileSync(jobPath + ".error.txt", "utf8").split("\n").slice(-8).join("\n") + "\n");
    }
  }
} else {
  process.stdout.write("\n!! no captures were written -- was Blender launched under the RenderDoc hook?\n");
}

// --- report ----------------------------------------------------------------

function median(values) {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.floor(ordered.length / 2)];
}

const pad = (text, width) => String(text).padEnd(width);
const padLeft = (text, width) => String(text).padStart(width);
const fixed = (value, digits = 2) => (value == null || Number.isNaN(value) ? "-" : value.toFixed(digits));

const byEngine = new Map();
for (const entry of stats.captures || []) {
  if (entry.error) continue;
  if (!byEngine.has(entry.label)) byEngine.set(entry.label, []);
  byEngine.get(entry.label).push(entry);
}

const names = engines.filter((e) => runs.has(e));
// Every bucket classify() can produce, so the per-kind rows sum to the total
// rather than quietly dropping time (real Blender GL frames carry Resolve and
// Present events, and glFlush lands in Other at ~0.4 ms -- not a rounding term).
const KINDS = ["Drawcall", "Dispatch", "Copy", "Clear", "Resolve", "Present", "Other"];

process.stdout.write("\n" + "=".repeat(84) + "\n");
const first = runs.get(names[0]);
process.stdout.write(
  `GPU TRACE: ${(first.sculpt_faces ?? 0).toLocaleString()} faces` +
  `${args.mode === "multires" ? ` at level ${first.level}` : ""}, ` +
  `paced stroke, ${args.frames} frames/arm, ${args.backend}\n`);
process.stdout.write("=".repeat(84) + "\n\n");

let header = pad("per captured frame (median)", 36);
for (const name of names) header += padLeft(name, 16);
process.stdout.write(header + "\n" + "-".repeat(header.length) + "\n");

function row(label, pick) {
  let line = pad(label, 36);
  for (const name of names) {
    const samples = (byEngine.get(name) || []).map(pick).filter((v) => v != null && !Number.isNaN(v));
    line += padLeft(samples.length ? fixed(median(samples)) : "-", 16);
  }
  process.stdout.write(line + "\n");
}

row("GPU time total (ms)", (c) => c.gpu_ms_total);
for (const kind of KINDS) {
  row(`  ${kind} GPU (ms)`, (c) => c.gpu_ms_by_kind?.[kind]);
}
row("actions", (c) => c.action_total);
for (const kind of KINDS) {
  row(`  ${kind} count`, (c) => c.actions?.[kind]);
}
row("draw vertices", (c) => c.draw_vertices);
row("draw instances", (c) => c.draw_instances);

process.stdout.write("\n");
let wallHeader = pad("wall clock (ms, under capture)", 36);
for (const name of names) wallHeader += padLeft(name, 16);
process.stdout.write(wallHeader + "\n" + "-".repeat(wallHeader.length) + "\n");
for (const [key, label] of [["cycle_ms", "per-dab cycle (push -> redrawn)"],
                            ["sculpt_view_ms", "viewport draw during sculpt"],
                            ["idle_view_ms", "viewport draw, no edit"]]) {
  let line = pad(`  ${label}`, 36);
  for (const name of names) line += padLeft(fixed(runs.get(name)?.[key]?.median), 16);
  process.stdout.write(line + "\n");
}
let phase = pad("  sculpt phase total (ms)", 36);
for (const name of names) phase += padLeft(fixed(runs.get(name)?.sculpt_phase_ms, 0), 16);
process.stdout.write(phase + "\n");

process.stdout.write("\n");
for (const name of names) {
  const result = runs.get(name);
  const frames = (byEngine.get(name) || []).length;
  process.stdout.write(
    `${pad(name, 14)} captures=${padLeft(frames, 3)}/${result.captures?.length ?? 0}` +
    `  api=${pad((byEngine.get(name) || [])[0]?.api ?? "-", 10)}` +
    `  deformed=${(result.surface_after?.peak_z ?? 0) > 1e-6}\n`);
  if (result.error) process.stdout.write(`${pad("", 14)} ERROR: ${String(result.error).split("\n").slice(-2)[0]}\n`);
}

const failed = (stats.captures || []).filter((c) => c.error);
if (failed.length) {
  process.stdout.write(`\n${failed.length} capture(s) failed to analyse, e.g.:\n  ${failed[0].error.split("\n").slice(-2)[0]}\n`);
}

process.stdout.write(`\nRaw results in ${args.out}\n`);
