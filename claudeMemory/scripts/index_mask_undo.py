# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Remove leaf and seek grouping scans found by the footprint review."""
from pathlib import Path

p = Path("engine/source/subdiv/grid_stroke_log.cc")
s = p.read_text()
a = s.index("  gen_ = 0;")
b = s.index("\n}\n", a)
s = s[:a] + "  captured_.clear();\n  debtCaptured_.clear();\n  leafCaptured_.clear();" + s[b:]
s = s.replace("  gen_++;\n", "")
a = s.index("  bool needPos = positions, needMask = maskToo;")
b = s.index("  s.leaves.append(LeafSnap());", a)
s = s[:a] + '''  auto &captured = leafCaptured_[leaf];
  const bool needPos = positions && !captured.position;
  const bool needMask = maskToo && captured.masks.add(maskId.levelToken);
  captured.position |= positions;
  if (!needPos && !needMask) {
    return;
  }
''' + s[b:]
s = s.replace("  open_ = false;\n  captured_.clear();", "  open_ = false;\n  leafCaptured_.clear();\n  captured_.clear();")
s = s.replace("  Vector<GridBlock *> swappedSession;", "  litestl::util::Map<int, Vector<int>> swappedSession;")
s = s.replace("      swappedSession.append(&b);", "      swappedSession[channel].append(b.grid);")
a = s.index("  for (size_t i = 0; i < swappedSession.size(); i++) {")
b = s.index("    mr->gridAttrs().refreshSamplesFromChannel(", a)
s = s[:a] + '''  for (auto &entry : swappedSession) {
    const auto &name = mr->store.channelName(entry.key);
    auto &grids = entry.value;
''' + s[b:]
p.write_text(s)
