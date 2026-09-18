# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fold implementation-review corrections into mask undo."""
from pathlib import Path

p = Path("engine/source/subdiv/grid_stroke_log.cc")
s = p.read_text()
s = s.replace("  leafStamp_.clear();", "  captured_.clear();\n  debtCaptured_.clear();\n  leafStamp_.clear();")
s = s.replace("  snapshotAttrDebt(s.preAttrDebt);", "  snapshotAttrDebt(s.preAttrDebt);\n  for (const auto &debt : s.preAttrDebt) {\n    debtCaptured_.add(debt.levelToken);\n  }")
a = s.index("  CapturedChannel *captured = nullptr;")
b = s.index("  s.blocks.append(captureBlock", a)
s = s[:a] + '''  if (debtCaptured_.add(id.levelToken)) {
    AttrDebt debt;
    static_cast<ChannelIdentity &>(debt) = id;
    debt.debt = d_->multires()->store.channelLevelDebt(d_->level(), channel);
    s.preAttrDebt.append(std::move(debt));
  }
  if (!captured_[id.levelToken].add(grid)) {
    return;
  }
''' + s[b:]
a = s.index("  LeafSnap *snap = nullptr;", s.index("void GridStrokeLog::captureLeaf"))
b = s.index("  const GridTree::Leaf &tl", a)
s = s[:a] + '''  const ChannelIdentity maskId = maskToo ? identity(d_->ensureMaskChannel(), d_->level()) :
                                          ChannelIdentity();
  bool needPos = positions, needMask = maskToo;
  if (leafStamp_[leaf] == gen_) {
    for (const auto &ls : s.leaves) {
      if (ls.leaf == leaf) {
        needPos &= !ls.hasPos;
        needMask &= !(ls.hasMask && ls.maskIdentity.levelToken == maskId.levelToken);
      }
    }
  }
  if (!needPos && !needMask) {
    return;
  }
  leafStamp_[leaf] = gen_;
  s.leaves.append(LeafSnap());
  LeafSnap *snap = &s.leaves.last();
  snap->leaf = leaf;
''' + s[b:]
s = s.replace("if (positions && !snap->hasPos)", "if (needPos)")
s = s.replace("if (maskToo && !snap->hasMask)", "if (needMask)")
s = s.replace("snap->maskIdentity = identity(d_->ensureMaskChannel(), d_->level());", "snap->maskIdentity = maskId;")
s = s.replace("  open_ = false;\n  Step &s", "  open_ = false;\n  captured_.clear();\n  debtCaptured_.clear();\n  Step &s")
s = s.replace("  s.postDebt = postDebt;", "  for (auto &fine : s.finerMask) {\n    fine.captured.clear();\n  }\n  s.postDebt = postDebt;")
# Discard fine cached domains before owning swaps or any drawing refresh.
s = s.replace("  for (auto &snap : s.finerMask) {\n    const int channel", "  mr->invalidateAbove(level);\n  for (auto &snap : s.finerMask) {\n    const int channel")
s = s.replace("  // Finer levels derive from this one's positions; the swapped state is new\n  // to them either way.\n  mr->invalidateAbove(level);", "  if (!s.finerMask.isEmpty()) {\n    mr->noteMaskChange();\n  }")
end = s.index("} // namespace sculptcore::subdiv")
s = s[:end] + '''size_t GridStrokeLog::retainedBytes() const
{
  size_t n = bytes();
  for (const Step &s : steps_) {
    n += sizeof(Step);
    for (const auto &leaf : s.leaves) {
      n += sizeof(LeafSnap) + leaf.maskIdentity.channel.capacity() + 1;
    }
    for (const auto &b : s.blocks) {
      n += sizeof(GridBlock) + b.channel.capacity() + 1;
    }
    for (const auto &fine : s.finerMask) {
      n += sizeof(FinerMask) + fine.channel.capacity() + 1;
      n += fine.state.chunks.size() * sizeof(Vector<float>);
      for (const auto &b : fine.blocks) {
        n += sizeof(GridBlock) + b.channel.capacity() + 1;
      }
    }
    for (const auto &debt : s.preAttrDebt) {
      n += sizeof(AttrDebt) + debt.channel.capacity() + 1;
    }
    for (const auto &debt : s.postAttrDebt) {
      n += sizeof(AttrDebt) + debt.channel.capacity() + 1;
    }
  }
  return n;
}

''' + s[end:]
p.write_text(s)
