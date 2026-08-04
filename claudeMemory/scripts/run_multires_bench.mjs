// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

// Runs bench_multires_native.py against each Blender build in turn and prints a
// comparison, using the first configuration as the baseline.
//
//   node claudeMemory/scripts/run_multires_bench.mjs \
//        --main C:/dev/blender/build_windows_x64_clang_main/bin/blender.exe \
//        --fork C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe \
//        [--grid 64] [--level 4] [--repeats 1] [--out DIR]
//
// Three configurations are measured, because the fork build ships the
// SculptCore add-on always-enabled (even under --factory-startup, via
// .always_enable) and its depsgraph handler would otherwise be indistinguishable
// from a C++ regression:
//
//   main            stock main         -- the baseline
//   fork-noaddon    fork, add-on off   -- isolates the fork's 22 C++ commits
//   fork            fork, as shipped   -- what a user actually runs

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const SCRIPT = path.join(HERE, "bench_multires_native.py");

function parseArgs() {
  const out = { grid: 64, level: 4, repeats: 1, modes: "multires,mesh", out: path.join(HERE, "bench-results") };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, "");
    const value = argv[i + 1];
    if (["grid", "level", "repeats"].includes(key)) out[key] = Number(value), i++;
    else if (["main", "fork", "out", "modes"].includes(key)) out[key] = value, i++;
    else throw new Error(`unknown argument: ${argv[i]}`);
  }
  if (!out.main) throw new Error("--main <blender.exe> is required");
  return out;
}

const args = parseArgs();
mkdirSync(args.out, { recursive: true });

const configs = [{ name: "main", exe: args.main, disableAddon: false }];
if (args.fork) {
  configs.push({ name: "fork-noaddon", exe: args.fork, disableAddon: true });
  configs.push({ name: "fork", exe: args.fork, disableAddon: false });
}

function run(config, mode, repeat) {
  const label = `${mode}-${config.name}-r${repeat}`;
  const jsonPath = path.join(args.out, `${label}.json`);
  const blenderArgs = [
    "--factory-startup", "--no-window-focus", "-p", "0", "0", "1280", "800",
    "--python-exit-code", "1", "--python", SCRIPT, "--",
    "--out", jsonPath, "--label", label,
    "--grid", String(args.grid), "--level", String(args.level), "--mode", mode,
  ];
  if (config.disableAddon) blenderArgs.push("--disable-addon");

  process.stdout.write(`\n=== ${label} :: ${config.exe}\n`);
  const proc = spawnSync(config.exe, blenderArgs, { encoding: "utf8" });
  for (const line of (proc.stdout || "").split("\n")) {
    if (/\[bench\]|BENCH|Error|Traceback/.test(line)) process.stdout.write(`    ${line.trim()}\n`);
  }
  if (!existsSync(jsonPath)) {
    process.stdout.write(`    !! no result written (exit ${proc.status})\n`);
    return null;
  }
  return JSON.parse(readFileSync(jsonPath, "utf8"));
}

const modes = args.modes.split(",").map((m) => m.trim()).filter(Boolean);
const results = [];
for (const mode of modes) {
  for (let repeat = 1; repeat <= args.repeats; repeat++) {
    for (const config of configs) {
      const result = run(config, mode, repeat);
      if (result) results.push({ config: config.name, repeat, ...result });
    }
  }
}

// --- report ---------------------------------------------------------------

// Median of medians across repeats: robust against one noisy run on a desktop
// that is not a dedicated benchmark machine.
function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.floor(ordered.length / 2)];
}

const METRICS = [
  ["stroke_ms", "median", "brush_stroke operator"],
  ["stroke_redraw_ms", "median", "edit -> redrawn (interactive)"],
  ["sculpt_view_ms", "median", "viewport draw after edit"],
  ["idle_view_ms", "median", "viewport draw, no edit"],
  ["idle_frame_ms", "median", "full frame, no edit (VSYNC-CAPPED)"],
  ["bvh_rebuild_ms", "median", "sculpt.optimize"],
  ["subdivide_ms_total", null, "multires subdivide to level"],
];

function value(result, key, field) {
  const entry = result[key];
  if (entry == null) return null;
  return field ? entry[field] : entry;
}

const pad = (text, width) => String(text).padEnd(width);
const padLeft = (text, width) => String(text).padStart(width);

for (const mode of modes) {
  const inMode = results.filter((r) => r.mode === mode);
  if (!inMode.length) continue;

  const byConfig = new Map();
  for (const result of inMode) {
    if (!byConfig.has(result.config)) byConfig.set(result.config, []);
    byConfig.get(result.config).push(result);
  }
  const names = [...byConfig.keys()];
  const first = byConfig.get(names[0])[0];

  process.stdout.write("\n" + "=".repeat(84) + "\n");
  process.stdout.write(
    `${mode === "multires" ? "MULTIRES" : "MESH (control, no multires)"}: ` +
    `${first.sculpt_faces.toLocaleString()} faces` +
    `${mode === "multires" ? ` at level ${first.level}` : ""}, ` +
    `${(first.surface_before?.verts ?? 0).toLocaleString()} evaluated verts\n`);
  process.stdout.write("=".repeat(84) + "\n\n");

  let header = pad("metric (ms, median)", 36);
  for (const name of names) header += padLeft(name, 16);
  process.stdout.write(header + "\n" + "-".repeat(header.length) + "\n");

  for (const [key, field, description] of METRICS) {
    const base = median(byConfig.get(names[0]).map((r) => value(r, key, field)).filter((v) => v != null));
    if (base == null) continue;
    let row = pad(description, 36);
    for (const name of names) {
      const samples = byConfig.get(name).map((r) => value(r, key, field)).filter((v) => v != null);
      if (!samples.length) { row += padLeft("-", 16); continue; }
      const current = median(samples);
      const cell = name === names[0]
        ? current.toFixed(2)
        : `${current.toFixed(2)} (${current >= base ? "+" : ""}${(((current - base) / base) * 100).toFixed(0)}%)`;
      row += padLeft(cell, 16);
    }
    process.stdout.write(row + "\n");
  }

  process.stdout.write("\n");
  for (const name of names) {
    const result = byConfig.get(name)[0];
    // addon_after only exists when --disable-addon ran; otherwise report the
    // state as found. brush_prop / depsgraph handler count are the reliable
    // signals -- the add-on's mode class does not show up as an RNA subclass.
    const addon = result.addon_after ?? result.addon_before ?? {};
    process.stdout.write(
      `${pad(name, 14)} peak RSS ${padLeft(((result.memory?.peak_working_set ?? 0) / 1e6).toFixed(0), 5)} MB` +
      `  addon_live=${pad(!!addon.brush_prop, 6)} handlers=${addon.depsgraph_handlers}` +
      `  fork_api=${pad(!!addon.custom_mode_api, 6)}` +
      `  deformed=${(result.surface_after?.peak_z ?? 0) > 1e-6}` +
      `  undo=${((result.undo_memory ?? 0) / 1e6).toFixed(2)}MB\n`);
    if (result.error) process.stdout.write(`${pad("", 14)} ERROR: ${String(result.error).split("\n")[0]}\n`);
  }
}

writeFileSync(path.join(args.out, "summary.json"), JSON.stringify(results, null, 2));
process.stdout.write(`\nRaw results in ${args.out}\n`);
