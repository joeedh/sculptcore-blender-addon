// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/* Headed sweep of the multires draw-node granularity.
 *
 * The headless sweep (bench_multires_tuning.py) can see the CPU half of the
 * draw path — GridDrawSource refill — but not the half that decides how big a
 * draw node should be: the host's per-node batch sync and draw calls. This
 * drives bench_multires_sc.py (GUI, event-simulated strokes) once per config
 * and reports idle_view_ms / sculpt_view_ms alongside stroke cost.
 *
 * Configs are passed to the engine as the multires_tuning.cc sweep env vars,
 * so no rebuild is needed between them.
 *
 * Runs are INTERLEAVED (config order repeats as a block: A B C, A B C, …)
 * because this machine's display pacing has been observed to flip 30<->60 Hz
 * between batches; a block-per-config layout would alias that drift onto the
 * config. idle_frame_ms is reported so a flip is visible.
 *
 *   node claudeMemory/scripts/run_tuning_headed.mjs \
 *     --blender C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe \
 *     --grid 64 --level 4 --repeats 2 \
 *     --configs auto,fixed,tris=2048,tris=8192,tris=32768
 */

import {spawnSync} from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const BENCH = path.join(HERE, "bench_multires_sc.py");

function parseArgs() {
  const out = {
    blender: "C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe",
    grid: 64, level: 4, repeats: 2, strokes: 20,
    configs: "auto,fixed", outDir: path.join(HERE, "tune-results", "headed"),
  };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, "");
    const val = argv[++i];
    if (!(key in out)) throw new Error(`unknown option --${key}`);
    out[key] = typeof out[key] === "number" ? Number(val) : val;
  }
  return out;
}

/** 'leaf=1024;tris=8192' / 'auto' / 'fixed' -> env overrides. */
function configEnv(spec) {
  if (spec === "auto") return {};
  if (spec === "fixed") return {SC_MR_AUTOTUNE: "0"};
  const env = {};
  for (const part of spec.split(";")) {
    const [key, val] = part.split("=");
    const name = {leaf: "SC_MR_LEAF_TARGET", tris: "SC_MR_DRAW_TRIS",
                  slotleaf: "SC_MR_SLOT_LEAF"}[key.trim()];
    if (!name) throw new Error(`unknown config key '${key}' in '${spec}'`);
    env[name] = val.trim();
  }
  return env;
}

const ARGS = parseArgs();
const configs = ARGS.configs.split(",").map((s) => s.trim()).filter(Boolean);
fs.mkdirSync(ARGS.outDir, {recursive: true});

const rows = [];
for (let rep = 0; rep < ARGS.repeats; rep++) {
  for (const spec of configs) {
    const label = `${spec}#${rep}`;
    const out = path.join(ARGS.outDir, `${spec.replace(/[=;]/g, "_")}-${rep}.json`);
    process.stdout.write(`[headed] ${label} … `);
    const res = spawnSync(ARGS.blender, [
      "--factory-startup", "--no-window-focus", "-p", "0", "0", "1280", "800",
      "--enable-event-simulate", "--python-exit-code", "1", "--python", BENCH, "--",
      "--out", out, "--label", label, "--engine", "sculptcore",
      "--grid", String(ARGS.grid), "--level", String(ARGS.level),
      "--mode", "multires", "--strokes", String(ARGS.strokes),
    ], {env: {...process.env, ...configEnv(spec)}, encoding: "utf8"});
    if (res.status !== 0) {
      console.log(`FAILED (exit ${res.status})`);
      console.log((res.stdout || "").split("\n").slice(-25).join("\n"));
      continue;
    }
    const r = JSON.parse(fs.readFileSync(out, "utf8"));
    if (r.error) {
      console.log(`ERROR: ${String(r.error).split("\n")[0]}`);
      continue;
    }
    rows.push({spec, rep, r});
    console.log(`idle_view ${r.idle_view_ms.median.toFixed(2)} ms  ` +
                `sculpt_view ${(r.sculpt_view_ms?.median ?? NaN).toFixed(2)} ms  ` +
                `stroke ${(r.stroke_ms?.median ?? NaN).toFixed(1)} ms`);
  }
}

const cell = (v, d = 2) => (v === undefined || v === null || Number.isNaN(v) ? "  -  " : v.toFixed(d));
console.log(`\n${"config".padEnd(16)} rep  idle_view  idle_frame  sculpt_view  stroke  sculpt_phase  enter`);
for (const {spec, rep, r} of rows) {
  console.log(
    `${spec.padEnd(16)} ${String(rep).padEnd(3)} ` +
    `${cell(r.idle_view_ms?.median).padStart(9)} ` +
    `${cell(r.idle_frame_ms?.median).padStart(11)} ` +
    `${cell(r.sculpt_view_ms?.median).padStart(12)} ` +
    `${cell(r.stroke_ms?.median, 1).padStart(7)} ` +
    `${cell(r.sculpt_phase_ms, 0).padStart(13)} ` +
    `${cell(r.enter_mode_ms, 0).padStart(6)}`);
}

const summary = path.join(ARGS.outDir, "summary.json");
fs.writeFileSync(summary, JSON.stringify(rows.map(({spec, rep, r}) => ({
  spec, rep, idle_view_ms: r.idle_view_ms, idle_frame_ms: r.idle_frame_ms,
  sculpt_view_ms: r.sculpt_view_ms, stroke_ms: r.stroke_ms,
  sculpt_phase_ms: r.sculpt_phase_ms, enter_mode_ms: r.enter_mode_ms,
  surface_after: r.surface_after,
})), null, 1));
console.log(`\nwrote ${summary}`);
