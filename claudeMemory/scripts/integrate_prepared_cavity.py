# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "engine/source/brush"
for stem in ("brush_executor", "grid_executor"):
    path = root / (stem + ".h")
    text = path.read_text(encoding="utf-8")
    text = text.replace('#include "automask.h"', '#include "automask.h"\n#include "prepared_cavity.h"', 1)
    token = "  Brush *brush" + (" = nullptr;" if stem == "grid_executor" else ";")
    text = text.replace(token, token + "\n  PreparedCavityCache preparedCavity;\n  bool preparedCavityActive = false;", 1)
    begin = "  void beginStep(" + (")" if stem == "grid_executor" else "bool hasDyntopo)") + "\n  {"
    text = text.replace(begin, begin + "\n    preparedCavity.reset();", 1)
    if stem == "grid_executor":
        text = text.replace("  void attach(subdiv::GridLevelDomain *d)\n  {",
                            "  void attach(subdiv::GridLevelDomain *d)\n  {\n    preparedCavity.reset();", 1)
    grid = stem == "grid_executor"
    condition = "if (brush->automask_cavity" + (") {" if grid else " && nodes.size() > 0) {")
    geometry = "domain" if grid else "nodes[0]->data->m"
    topology = "attachedGeneration_" if grid else "m->topo_stamp"
    capacity = "domain->vertCount()" if grid else "m->v.count"
    source = "GridCavitySrc{domain}" if grid else "MeshCavitySrc{m}"
    vertices = "tree->leaves[node->leaf].ownedVerts" if grid else "node->data->unique_verts"
    position = "domain->pos()[v]" if grid else "m->v.co[v]"
    nodes = "nodeSpan" if grid else "nodes"
    preamble = "" if grid else "      auto *m = nodes[0]->data->m;\n"
    body = f'''if (preparedCavityActive && brush->automask_cavity && {nodes}.size()) {{
{preamble}      preparedCavity.beginGeometry({geometry}, {topology}, {capacity});
      PreparedCavityCache::Entry *entry = nullptr;
      for (auto *node : {nodes}) {{
        for (int v : {vertices}) {{
          float3 contact = {position};
          if (nonAccum && cmd.accumulable && !cmd.relaxesBase && ctx.dispVec &&
              ctx.dispGen && ctx.dispGen->safe_get(v) == int(ctx.strokeGen))
            contact -= ctx.dispVec->safe_get(v);
          if (brush->falloffDist(contact - ctx.surfacePos, ctx.surfaceNo) < 1.0f) {{
            if (!entry)
              entry = &preparedCavity.entry(*brush);
            preparedCavity.fill(*entry, {source}, v);
          }} else {{
            preparedCavity.write(v, 1.0f);
          }}
        }}
      }}
      ctx.automaskFactor = preparedCavity.active();
      ctx.automaskEnabled = entry != nullptr;
    }} else '''
    assert condition in text
    text = text.replace(condition, body + condition, 1)
    path.write_text(text, encoding="utf-8")
    path = root / (stem + ".cc")
    text = path.read_text(encoding="utf-8")
    text = text.replace("brush.automask_cavity || executor.previewActive()", "executor.previewActive()")
    text = text.replace("brush->automask_cavity || attachedMultires_", "attachedMultires_")
    # Scope the prepared cache only after all candidate validation succeeds.
    if grid:
        text = text.replace("    execStage(command, origin, normal);",
                            "    ScopedPreparedCavity cavityScope(preparedCavityActive);\n    execStage(command, origin, normal);")
        text = text.replace("    for (size_t i = 0; i < commands.size(); i++) {",
                            "    ScopedPreparedCavity cavityScope(preparedCavityActive);\n    for (size_t i = 0; i < commands.size(); i++) {")
    else:
        text = text.replace("    if (brushNeedsLiveLinks(brushType) || keepTopoThawed) {", '''    if (brush->automask_cavity) {
      if (mesh->topo_frozen && !mesh->topo_cache.valid(*mesh))
        mesh->thawTopo();
      mesh->topo_cache.ensureRing1(*mesh);
    }
    if (brushNeedsLiveLinks(brushType) || keepTopoThawed) {''', 1)
        text = text.replace("    if (needsLive) {", '''    bool needsCavity = false;
    for (size_t i = 0; i < prepared.stages.size(); i++) {
      if (prepared.radii[i] > 0)
        for (const auto &value : prepared.stages[i].values())
          needsCavity |= value.name == string("automask_cavity") && value.value != 0;
    }
    if (needsCavity) {
      if (mesh->topo_frozen && !mesh->topo_cache.valid(*mesh))
        mesh->thawTopo();
      mesh->topo_cache.ensureRing1(*mesh);
    }
    if (needsLive) {''', 1)
        text = text.replace("    exec(command,", "    ScopedPreparedCavity cavityScope(preparedCavityActive);\n    exec(command,", 1)
        text = text.replace("    for (size_t i = 0; i < commands.size(); i++) {",
                            "    ScopedPreparedCavity cavityScope(preparedCavityActive);\n    for (size_t i = 0; i < commands.size(); i++) {")
    path.write_text(text, encoding="utf-8")
