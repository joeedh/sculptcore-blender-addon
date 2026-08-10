// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Bucket a bench_multires_sc.py --wall-trace timeline into labeled wall time.
//
//   node analyze_walltrace.mjs <result.json> [...]
//
// Every elementary segment of the sculpt phase is assigned to the highest-
// priority span covering it (op > dg > dgeval > draw > step > GAP), so nested
// spans (the addon dg handler inside the dgeval bracket, a dgeval inside a
// modal call) are not double counted. Reported per stroke (push-to-push) and
// as phase totals.

import fs from 'node:fs';

const PRIORITY = ['op:invoke', 'op:modal', 'dg', 'dgeval', 'draw', 'step'];
const label = (k) => (k.startsWith('op:') ? 'op' : k);

for (const file of process.argv.slice(2)) {
  const j = JSON.parse(fs.readFileSync(file, 'utf8'));
  const rec = j.wall_trace;
  if (!rec) { console.log(`${file}: no wall_trace`); continue; }

  const spans = rec.filter(([k]) => k !== 'push')
    .map(([k, t, d]) => ({ k, t0: t, t1: t + d }))
    .filter((s) => s.t1 > s.t0);
  const pushes = rec.filter(([k]) => k === 'push').map(([, t]) => t);
  const tEnd = Math.max(...spans.map((s) => s.t1), ...pushes);

  // Elementary segments between all boundaries, claimed by priority.
  const cuts = [...new Set([0, tEnd, ...pushes,
    ...spans.flatMap((s) => [s.t0, s.t1])])].sort((a, b) => a - b);
  const strokes = pushes.map((t, i) => ({
    t0: t, t1: i + 1 < pushes.length ? pushes[i + 1] : tEnd, buckets: {},
  }));
  const totals = {};
  for (let i = 0; i + 1 < cuts.length; i++) {
    const a = cuts[i], b = cuts[i + 1];
    if (b <= a) continue;
    const mid = (a + b) / 2;
    const covering = spans.filter((s) => s.t0 <= mid && mid < s.t1);
    covering.sort((x, y) => PRIORITY.indexOf(x.k) - PRIORITY.indexOf(y.k));
    const key = covering.length ? label(covering[0].k) : 'GAP';
    totals[key] = (totals[key] ?? 0) + (b - a);
    const st = strokes.find((s) => s.t0 <= mid && mid < s.t1);
    if (st) st.buckets[key] = (st.buckets[key] ?? 0) + (b - a);
  }

  const keys = [...new Set([...Object.keys(totals)])].sort(
    (a, b) => (totals[b] ?? 0) - (totals[a] ?? 0));
  console.log(`\n=== ${file} (engine=${j.engine}) ===`);
  console.log(`sculpt_phase_ms ${j.sculpt_phase_ms?.toFixed(1)}  strokes ${pushes.length}` +
    `  timeline span ${tEnd.toFixed(1)} ms`);
  console.log('phase totals (ms, and per-stroke over ' + pushes.length + '):');
  for (const k of keys) {
    console.log(`  ${k.padEnd(7)} ${totals[k].toFixed(1).padStart(8)}  ` +
      `${(totals[k] / pushes.length).toFixed(2).padStart(7)} /stroke`);
  }
  // Per-stroke table (skip stroke 0, often degenerate).
  console.log('per-stroke:  ' + keys.map((k) => k.padStart(8)).join('') + '     wall');
  strokes.forEach((s, i) => {
    const wall = s.t1 - s.t0;
    console.log(`  stroke ${String(i).padStart(2)} ` +
      keys.map((k) => (s.buckets[k] ?? 0).toFixed(1).padStart(8)).join('') +
      `  ${wall.toFixed(1).padStart(7)}`);
  });

  // Structure of one representative stroke: ordered spans with gaps.
  const mids = strokes.slice(3, 4);
  for (const st of mids) {
    console.log(`raw timeline of stroke 3 [${st.t0.toFixed(1)}..${st.t1.toFixed(1)}]:`);
    const inside = spans.filter((s) => s.t1 > st.t0 && s.t0 < st.t1)
      .sort((a, b) => a.t0 - b.t0);
    let cursor = st.t0;
    for (const s of inside) {
      if (s.t0 - cursor > 0.5) {
        console.log(`    ... gap ${(s.t0 - cursor).toFixed(2)} ms`);
      }
      console.log(`    ${s.k.padEnd(10)} +${(s.t0 - st.t0).toFixed(2).padStart(8)}  ` +
        `dur ${(s.t1 - s.t0).toFixed(2)}`);
      cursor = Math.max(cursor, s.t1);
    }
    if (st.t1 - cursor > 0.5) console.log(`    ... gap ${(st.t1 - cursor).toFixed(2)} ms (tail)`);
  }
}
