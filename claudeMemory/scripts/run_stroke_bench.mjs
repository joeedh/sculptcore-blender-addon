// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/* Interleaved native-vs-SculptCore realistic-stroke A/B.
 *
 * Drives bench_multires_sc.py (wall-clock device-rate strokes in a headed
 * Blender) once per engine per round, INTERLEAVED (native, sculptcore,
 * native, sculptcore, ...): this machine's display pacing has been observed
 * to flip 30<->60 Hz between batches, and a block-per-engine layout aliases
 * that drift onto the engine (a separated A/B here once faked a 1.9x speedup
 * that interleaving showed was ~1.6%). idle_frame_ms is reported so a flip
 * is visible.
 *
 * vsync defaults to ON: the headline metric is the presented-frame interval
 * a user feels, and users run with vsync. Pass --vsync off to un-cap the
 * frame rate when attributing where the time goes rather than judging feel.
 *
 *   node claudeMemory/scripts/run_stroke_bench.mjs \
 *     --blender C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe \
 *     --grid 64 --level 4 --repeats 2 [--strokes 12] [--event-hz 200] \
 *     [--stroke-secs 1.2] [--vsync on] [--engines native,sculptcore]
 */

import {spawnSync} from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const BENCH = path.join(HERE, "bench_multires_sc.py");

function parseArgs() {
  const out = {
    blender: "C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe",
    grid: 64, level: 4, repeats: 2, strokes: 12,
    eventHz: 200, strokeSecs: 1.2, gapSecs: 0.3, brushSize: 50,
    mode: "multires", vsync: "on", engines: "native,sculptcore",
    timeout: 900,
    outDir: path.join(HERE, "stroke-bench-results"),
  };
  const alias = {"event-hz": "eventHz", "stroke-secs": "strokeSecs", "gap-secs": "gapSecs",
                 "brush-size": "brushSize"};
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const raw = argv[i].replace(/^--/, "");
    const key = alias[raw] || raw;
    if (!(key in out)) throw new Error(`unknown option --${raw}`);
    const val = argv[++i];
    out[key] = typeof out[key] === "number" ? Number(val) : val;
  }
  return out;
}

const ARGS = parseArgs();
const engines = ARGS.engines.split(",").map((s) => s.trim()).filter(Boolean);
fs.mkdirSync(ARGS.outDir, {recursive: true});

const rows = [];
for (let rep = 0; rep < ARGS.repeats; rep++) {
  for (const engine of engines) {
    const label = `${engine}#${rep}`;
    const out = path.join(ARGS.outDir, `${engine}-${rep}.json`);
    process.stdout.write(`[stroke-bench] ${label} … `);
    const res = spawnSync(ARGS.blender, [
      "--factory-startup", "--no-window-focus", "-p", "0", "0", "1280", "800",
      "--enable-event-simulate", "--gpu-vsync", ARGS.vsync,
      "--python-exit-code", "1", "--python", BENCH, "--",
      "--out", out, "--label", label, "--engine", engine,
      "--grid", String(ARGS.grid), "--level", String(ARGS.level),
      "--mode", ARGS.mode, "--strokes", String(ARGS.strokes),
      "--event-hz", String(ARGS.eventHz), "--stroke-secs", String(ARGS.strokeSecs),
      "--gap-secs", String(ARGS.gapSecs), "--brush-size", String(ARGS.brushSize),
    ], {encoding: "utf8", timeout: ARGS.timeout * 1000});
    if (res.status !== 0 || !fs.existsSync(out)) {
      console.log(`FAILED (exit ${res.status})`);
      console.log((res.stdout || "").split("\n").slice(-25).join("\n"));
      continue;
    }
    const r = JSON.parse(fs.readFileSync(out, "utf8"));
    if (r.error) {
      console.log(`ERROR: ${String(r.error).split("\n").filter(Boolean).slice(-1)[0]}`);
      continue;
    }
    rows.push({engine, rep, r});
    console.log(`frame ${r.stroke_frame_ms.median.toFixed(1)}/${r.stroke_frame_ms.p90.toFixed(1)} ms  ` +
                `latency ${r.latency_ms.median.toFixed(1)} ms  ` +
                `wall ${(r.stroke_wall_ms.median / 1000).toFixed(2)} s`);
  }
}

const cell = (v, d = 1) => (v === undefined || v === null || Number.isNaN(v) ? "  -  " : v.toFixed(d));
console.log(`\n${"engine".padEnd(12)} rep  frame_med  frame_p90  frame_max  latency  wall_ms  frames/st  dabs  idle_frame`);
for (const {engine, rep, r} of rows) {
  console.log(
    `${engine.padEnd(12)} ${String(rep).padEnd(3)} ` +
    `${cell(r.stroke_frame_ms?.median).padStart(9)} ` +
    `${cell(r.stroke_frame_ms?.p90).padStart(10)} ` +
    `${cell(r.stroke_frame_ms?.max).padStart(10)} ` +
    `${cell(r.latency_ms?.median).padStart(8)} ` +
    `${cell(r.stroke_wall_ms?.median, 0).padStart(8)} ` +
    `${cell(r.frames_per_stroke?.median, 0).padStart(10)} ` +
    `${cell(r.dabs_per_stroke?.median, 0).padStart(5)} ` +
    `${cell(r.idle_frame_ms?.median).padStart(11)}`);
}

// Pooled medians per engine, so run-to-run scatter reads at a glance.
function median(vals) {
  if (!vals.length) return NaN;
  const s = [...vals].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}
console.log("");
for (const engine of engines) {
  const mine = rows.filter((row) => row.engine === engine);
  if (!mine.length) continue;
  const pick = (key, stat) => median(mine.map(({r}) => r[key]?.[stat]).filter((v) => v != null));
  console.log(
    `${engine.padEnd(12)} pooled: frame ${cell(pick("stroke_frame_ms", "median"))}` +
    `/${cell(pick("stroke_frame_ms", "p90"))} ms  latency ${cell(pick("latency_ms", "median"))} ms  ` +
    `wall ${cell(pick("stroke_wall_ms", "median"), 0)} ms  ` +
    `events in/betw ${mine.map(({r}) => `${r.events?.moves}/${r.events?.inbetween}`).join(" ")}`);
}

const summary = path.join(ARGS.outDir, "summary.json");
fs.writeFileSync(summary, JSON.stringify(rows.map(({engine, rep, r}) => ({
  engine, rep,
  stroke_frame_ms: r.stroke_frame_ms, latency_ms: r.latency_ms,
  stroke_wall_ms: r.stroke_wall_ms, frames_per_stroke: r.frames_per_stroke,
  stroke_ms: r.stroke_ms, dabs_per_stroke: r.dabs_per_stroke, events: r.events,
  idle_frame_ms: r.idle_frame_ms, idle_view_ms: r.idle_view_ms,
  sculpt_view_ms: r.sculpt_view_ms, sculpt_phase_ms: r.sculpt_phase_ms,
  enter_mode_ms: r.enter_mode_ms, surface_after: r.surface_after,
})), null, 1));
console.log(`\nwrote ${summary}`);
