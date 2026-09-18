# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed owner-correct native unified-setting notification fix."""
from pathlib import Path

path = Path('C:/dev/blender/main/source/blender/makesrna/intern/rna_sculpt_paint.cc')
source = path.read_text(encoding='utf-8')
before = '''static void rna_UnifiedPaintSettings_update(bContext *C, PointerRNA * /*ptr*/)
{
  const Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  Brush *br = BKE_paint_brush(BKE_paint_get_active(*bmain, scene, view_layer));
  /* TODO: Verify if tagging the brush for these settings being changed is correct. */
  WM_main_add_notifier(NC_BRUSH | NA_EDITED, br);
  WM_main_add_notifier(NC_SCENE | ND_TOOLSETTINGS, scene);
}'''
after = '''static void rna_UnifiedPaintSettings_update(bContext * /*C*/, PointerRNA *ptr)
{
  /* Unified settings belong to their Scene, including when edited from another context. */
  ID *owner = ptr->owner_id;
  if (owner == nullptr) {
    return;
  }
  BLI_assert(GS(owner->name) == ID_SCE);
  WM_main_add_notifier(NC_SCENE | ND_TOOLSETTINGS, owner);
}'''
assert source.count(before) == 1, 'Expected callback changed; inspect before applying'
path.write_text(source.replace(before, after), encoding='utf-8', newline='\n')
print('Updated', path)
