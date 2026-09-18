# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed mask undo implementation to its known source seams."""
from pathlib import Path

path = Path("engine/source/subdiv/grid_stroke_log.cc")
source = path.read_text()
source = source.replace("  gridStamp_.clear();\n  gridChannels_.clear();\n", "")
source = source.replace("    gridStamp_.resize(d_->gridCount());\n    gridChannels_.resize(d_->gridCount());\n", "")
source = source.replace("    for (int i = 0; i < int(gridStamp_.size()); i++) {\n      gridStamp_[i] = 0;\n      gridChannels_[i] = 0;\n    }\n", "")
start = source.index("void GridStrokeLog::captureGridBlock(")
end = source.index("void GridStrokeLog::captureLeaf(", start)
source = source[:start] + '''GridStrokeLog::ChannelIdentity GridStrokeLog::identity(int channel, int level) const
{
  const auto &ch = d_->multires()->store.channels_[channel];
  return {ch.name, ch.incarnation, ch.levels[level - 1].incarnation, level};
}

int GridStrokeLog::resolve(const ChannelIdentity &id) const
{
  const auto &store = d_->multires()->store;
  int channel = store.findChannel(id.channel);
  if (channel < 0 || id.level < 1 || id.level > store.levelCount()) {
    return -1;
  }
  const auto &ch = store.channels_[channel];
  return ch.incarnation == id.channelToken &&
                 ch.levels[id.level - 1].incarnation == id.levelToken ? channel : -1;
}

GridStrokeLog::GridBlock GridStrokeLog::captureBlock(int grid, int channel, int level)
{
  auto &store = d_->multires()->store;
  int floats = store.channelElemsPerGrid(level, channel) * store.channelElemSize(channel);
  GridBlock b;
  static_cast<ChannelIdentity &>(b) = identity(channel, level);
  b.grid = grid;
  b.data.resize(floats);
  const float *src = store.elem(level, channel, grid, 0, 0);
  std::memcpy(b.data.data(), src, size_t(floats) * sizeof(float));
  return b;
}

void GridStrokeLog::captureGridBlock(Step &s, int grid, int channel)
{
  const auto id = identity(channel, d_->level());
  CapturedChannel *captured = nullptr;
  for (auto &entry : s.captured) {
    if (entry.levelToken == id.levelToken) {
      captured = &entry;
      break;
    }
  }
  if (!captured) {
    s.captured.append(CapturedChannel());
    captured = &s.captured.last();
    captured->levelToken = id.levelToken;
    bool known = false;
    for (const auto &debt : s.preAttrDebt) {
      known |= debt.levelToken == id.levelToken;
    }
    if (!known) {
      AttrDebt debt;
      static_cast<ChannelIdentity &>(debt) = id;
      debt.debt = d_->multires()->store.channelLevelDebt(d_->level(), channel);
      s.preAttrDebt.append(std::move(debt));
    }
  }
  if (captured->grids.contains(grid)) {
    return;
  }
  captured->grids.add(grid);
  s.blocks.append(captureBlock(grid, channel, d_->level()));
}

void GridStrokeLog::captureFinerMask(std::span<const int> grids, int channel)
{
  Assert(open_, "captureFinerMask inside a step");
  auto &store = d_->multires()->store;
  Assert(channel >= 0 && channel < store.channelCount(), "mask channel exists before fold");
  const auto &ch = store.channels_[channel];
  Assert(ch.name == litestl::util::string(GridLevelDomain::kMaskChannelName) &&
             ch.type == mesh::AttrType::FLOAT && ch.domain == GridElemDomain::Vertex &&
             ch.floatsPerElem == 1, "compatible mask channel");
  if (grids.empty()) {
    return;
  }
  Step &s = steps_.last();
  for (int level = d_->level() + 1; level <= store.levelCount(); level++) {
    const auto id = identity(channel, level);
    FinerMask *snap = nullptr;
    for (auto &entry : s.finerMask) {
      if (entry.levelToken == id.levelToken) {
        snap = &entry;
        break;
      }
    }
    if (!snap) {
      s.finerMask.append(FinerMask());
      snap = &s.finerMask.last();
      static_cast<ChannelIdentity &>(*snap) = id;
      snap->debt = store.channelLevelDebt(level, channel);
      snap->wholeLevel = !store.channelLevelAllocated(level, channel);
      if (snap->wholeLevel) {
        // This copy holds no buffers and preserves the actual empty metadata.
        snap->state = store.channels_[channel].levels[level - 1];
      }
    }
    if (!snap->wholeLevel) {
      for (int grid : grids) {
        if (!snap->captured.contains(grid)) {
          snap->captured.add(grid);
          snap->blocks.append(captureBlock(grid, channel, level));
        }
      }
    }
  }
}

''' + source[end:]
source = source.replace("    snap->hasMask = true;", "    snap->maskIdentity = identity(d_->ensureMaskChannel(), d_->level());\n    snap->hasMask = true;")
start = source.index("void GridStrokeLog::snapshotAttrDebt(")
end = source.index("void GridStrokeLog::applySwap(", start)
source = source[:start] + '''void GridStrokeLog::snapshotAttrDebt(Vector<AttrDebt> &out)
{
  const auto &store = d_->multires()->store;
  out.clear();
  for (int c = 0; c < store.channelCount(); c++) {
    AttrDebt debt;
    static_cast<ChannelIdentity &>(debt) = identity(c, d_->level());
    debt.debt = store.channelLevelDebt(d_->level(), c);
    out.append(std::move(debt));
  }
}

void GridStrokeLog::applyAttrDebt(const Vector<AttrDebt> &debts)
{
  for (const auto &debt : debts) {
    int channel = resolve(debt);
    if (channel >= 0) {
      d_->multires()->store.setChannelLevelDebt(debt.level, channel, debt.debt);
    }
  }
}

''' + source[end:]
source = source.replace("    if (ls.hasMask) {", "    if (ls.hasMask && resolve(ls.maskIdentity) >= 0) {")
source = source.replace("const int channel = mr->store.findChannel(b.channel);", "const int channel = resolve(b);")
needle = "  if (touchedVerts.size() > 0) {"
pos = source.index(needle, source.index("void GridStrokeLog::applySwap("))
source = source[:pos] + '''  for (auto &snap : s.finerMask) {
    const int channel = resolve(snap);
    if (channel < 0) {
      continue;
    }
    auto &live = mr->store.channels_[channel].levels[snap.level - 1];
    if (snap.wholeLevel) {
      std::swap(snap.state, live);
    } else {
      for (auto &block : snap.blocks) {
        float *dst = mr->store.elem(snap.level, channel, block.grid, 0, 0);
        for (size_t i = 0; i < block.data.size(); i++) {
          std::swap(block.data[i], dst[i]);
        }
      }
      std::swap(snap.debt, live.downPending);
    }
  }

''' + source[pos:]
needle = "    for (const GridBlock &b : s.blocks) {\n      n += b.data.size() * sizeof(float);\n    }"
assert needle in source
source = source.replace(needle, needle + '''
    for (const auto &snap : s.finerMask) {
      for (const auto &block : snap.blocks) {
        n += block.data.size() * sizeof(float);
      }
      for (const auto &chunk : snap.state.chunks) {
        n += chunk.size() * sizeof(float);
      }
      n += snap.state.evicted.size();
    }''')
path.write_text(source)
