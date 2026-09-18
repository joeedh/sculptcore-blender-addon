# CurveMapping storage in external brush assets

Historical investigation (2026-09-15). The NodeTree approach was rejected.
The owned API has since been implemented; see [current reference](../codebase/generic-brush-properties.md).
The one-time probe is archived in addon commit `dbbd225`; commands below describe
that historical experiment and are not current test instructions.

Investigated 2026-09-15 against the local Blender fork source and
`C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe`
(reported Blender 5.3.0 Alpha, build hash Unknown).

## Conclusion

A Brush PropertyGroup can hold a real NodeTree ID reference, and Blender's
brush asset save/load machinery includes that node tree and its CurveMappings.
External asset packaging is viable. A node tree referenced only by name, or
reachable only from the scene, would not establish this brush dependency.

Using the node tree as authoritative curve storage still needs lifecycle work:
Revert Asset does not restore its contents in the tested build, scripted curve
edits do not automatically dirty the brush, and generic Brush.copy() shares the
tree. The dedicated brush asset Save As operators do copy it independently.

Recommendation: consider an owner-aware CurveMapping property in the fork's
add-on API. It should integrate storage, copying, file/asset serialization,
undo/revert, and owner update notifications, not merely expose construction of
an otherwise unowned CurveMapping. This remains an architectural recommendation;
no fork implementation was made.

An add-on-only alternative is to persist curve definitions directly in Brush
properties and use hidden nodes as temporary editor/evaluation caches. This
avoids external node-tree ownership but requires reliable editor-to-property
synchronization, dirty tracking, and cache reconstruction after revert/undo.

## Runtime evidence

Harness: `../scripts/probe_curve_asset_storage.py`.

It registers a PropertyGroup with a NodeTree PointerProperty on Brush and uses
a ShaderNodeFloatCurve in a standalone ShaderNodeTree. Tests use real
`brush.asset_save_as`, `brush.asset_activate`, `brush.asset_save`, and
`brush.asset_revert` operators. They run under factory startup and register a
scratch asset library in memory; user preferences are never saved.

| Check | Observed result |
| --- | --- |
| External Save As | Brush and node tree both reference the resulting `.asset.blend` |
| Fresh-process activation | Curve endpoint `0.625` restored; tree editable |
| Change endpoint to `0.375`, call CurveMapping.update() | Brush dirty flag remains false |
| Brush.update_tag() and view-layer update | Dirty flag still false in this headless test |
| Explicit Save Asset, fresh-process readback | Saved endpoint `0.375` restored |
| Generic Brush.copy() | Node tree shared |
| Save As into current-file asset library | Independent tree; copy edit leaves source unchanged |
| Save As into external asset library | Independent tree; copy edit leaves source unchanged |
| Edit saved endpoint `0.375` to `0.75`, Revert Asset | Reuses tree; endpoint incorrectly stays `0.75`; dirty flag false |
| Repeat revert in fresh process without duplicate brushes | Same failure; resulting tree has one user |
| Assign native brush strength to its existing value | Native update callback marks brush dirty |

The native-property self-assignment is diagnostic evidence, not a proposed
production notification API. No interactive curve-widget or undo test was run.
The process reported blocked writes to the optional global asset-index cache;
the actual asset operators and file readbacks succeeded inside the workspace.

Reproduce with a new scratch directory, running these phases in order:

```powershell
& 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe' --background --factory-startup --python-exit-code 1 --python claudeMemory/scripts/probe_curve_asset_storage.py -- create claudeMemory/tests/curve-asset-probe-new
& 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe' --background --factory-startup --python-exit-code 1 --python claudeMemory/scripts/probe_curve_asset_storage.py -- reload claudeMemory/tests/curve-asset-probe-new
& 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe' --background --factory-startup --python-exit-code 1 --python claudeMemory/scripts/probe_curve_asset_storage.py -- verify claudeMemory/tests/curve-asset-probe-new
```

Revert is reported as an observation rather than asserted successful, since it
currently fails to restore dependency contents. Successful process exit does
not mean all behavior in this investigation is correct.

## Source evidence in the sibling Blender checkout

* `source/blender/blenkernel/intern/asset_edit.cc`, `asset_write_in_library`:
  uses PartialWriteContext with MAKE_LOCAL, SET_FAKE_USER, ADD_DEPENDENCIES.
* `source/blender/blenkernel/intern/lib_query.cc`: traverses nested IDProperties
  for ID references and treats them as user-counted dependencies.
* `source/blender/makesdna/DNA_ID.h`, `ID_TYPE_SUPPORTS_ASSET_EDITABLE`: includes
  ID_NT, allowing node-tree dependencies in editable asset libraries.
* `source/blender/blenkernel/intern/brush.cc`, `BKE_brush_duplicate`: recursively
  duplicates ID dependencies and remaps references. The current-file brush
  asset Save As operator calls this, unlike generic ID.copy().
* `source/blender/blenkernel/intern/asset_edit.cc`, `asset_reload`: explicitly
  notes the missing single-datablock-and-dependencies reload API; deletes the
  brush and links it again. The existing node-tree ID survives and is reused.
* `source/blender/editors/render/render_update.cc`, `ED_render_id_flush_update`:
  brush updates mark brushes dirty; it does not generically propagate standalone
  node-tree changes through custom-property references to brush owners.

## Ownership requirements regardless of implementation

* Persist dormant local curves with the brush. Scene-inherited curves remain
  scene-owned; resolve them at runtime without capturing the scene's storage in
  the saved brush asset.
* Share immutable baked response tables freely. Editable storage needs explicit
  ownership so changing a copied brush cannot alter its source.
* A CurveMapping wrapper needs to propagate edits to its actual owning Brush
  or Scene, including when nested inside a PropertyGroup/CollectionProperty.
* Fork work, if chosen, should remain generic and engine-agnostic.
