# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Phased pointer/keyboard regression driver for the test-owned live editor."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "claudeMemory/tests" / os.environ.get("OWNED_CURVE_EDITOR_OUTPUT", "owned-curve-editor-final")
spec = importlib.util.spec_from_file_location("curve_editor_driver", ROOT / "tools/blender_debug.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
connection = json.loads((OUTPUT / "connection.json").read_text())
PREFIX = "t=bpy.app.driver_namespace['owned_editor_test']\n"


def run(code):
    result = helper.request(connection, "exec", PREFIX + code)
    with (OUTPUT / "controls.jsonl").open("a") as stream:
        stream.write(json.dumps({"code": code, "reply": result}) + "\n")
    assert result.get("ok"), result
    return result


def event(kind, value='PRESS', x=850, y=162, **kwargs):
    run("bpy.context.window_manager.windows[t['state'].get('window_index',0)].event_simulate(type={!r}, value={!r}, x={}, y={}, **{!r})".format(kind, value, x, y, kwargs))
    time.sleep(0.12)


def click(x, y):
    event('MOUSEMOVE', 'NOTHING', x, y)
    event('LEFTMOUSE', 'PRESS', x, y)
    event('LEFTMOUSE', 'RELEASE', x, y)
    time.sleep(0.15)


def key(kind, **kwargs):
    event(kind, 'PRESS', **kwargs)
    kwargs.pop("unicode", None)
    event(kind, 'RELEASE', **kwargs)


def number(x, y, value):
    click(x, y)
    click(x, y)
    key('A', ctrl=True, x=x, y=y)
    names = dict(zip("0123456789.-", ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE",
                                    "SIX", "SEVEN", "EIGHT", "NINE", "PERIOD", "MINUS")))
    for char in str(value):
        key(names[char], unicode=char, x=x, y=y)
    key('RET', x=x, y=y)


def open_dialog():
    event('MOUSEMOVE', 'NOTHING', 845, 165)
    click(860, 162)
    # Exit the initial text field without committing the popup.
    click(750, 480)


def apply():
    click(775, 32)
    time.sleep(0.4)


def check(name, assertion):
    run(assertion + "; t['state'].setdefault('checks', []).append({!r})".format(name))
    print("OWNED_EDITOR_CHECK " + name, flush=True)


def shot(name):
    run("t['screenshot']({!r})".format(name))


stage = sys.argv[-1]
if stage == "clip":
    key('ESC')
    open_dialog()
    click(650, 161)
    click(930, 161)
    number(1080, 99, 2)
    shot("valid_clipping_working")
    check("clip_controls_are_staged", "c=t['owner']().owned_editor_root.item.curve; assert c.use_clip and c.extend=='EXTRAPOLATED' and c.clip_max_y==1")
    apply()
    check("clipping_and_extension_apply_once", "c=t['owner']().owned_editor_root.item.curve; assert not c.use_clip and c.extend=='HORIZONTAL' and c.clip_max_y==2; assert t['state']['callbacks']==2")
    open_dialog()
    click(845, 448)
    key('RIGHTMOUSE', x=800, y=490)
    check("right_mouse_cancel", "assert t['state']['callbacks']==2")
    open_dialog()
    click(845, 448)
    click(100, 500)
    check("outside_click_cancel", "assert t['state']['callbacks']==2")
    shot("cancelled_controls")
elif stage == "points":
    run("t['state']['point_calls']=t['state']['callbacks']")
    open_dialog()
    event('MOUSEMOVE', 'NOTHING', 900, 350)
    event('LEFTMOUSE', 'PRESS', 900, 350, ctrl=True)
    event('LEFTMOUSE', 'RELEASE', 900, 350, ctrl=True)
    click(985, 191)
    shot("inserted_vector_point")
    apply()
    check("pointer_insertion_and_vector_handle_commit", "c=t['owner']().owned_editor_root.item.curve; assert len(c.curves[0].points)==3; assert c.curves[0].points[1].handle_type=='VECTOR'; assert t['state']['callbacks']==t['state']['point_calls']+1")
    open_dialog()
    click(900, 350)
    click(1115, 191)
    shot("selected_point_removed_working")
    # Removing the selection collapses two rows and moves Apply up by 62 pixels.
    click(775, 94)
    time.sleep(0.4)
    check("selected_point_remove_commit", "c=t['owner']().owned_editor_root.item.curve; assert len(c.curves[0].points)==2; assert t['state']['callbacks']==t['state']['point_calls']+2")
elif stage == "remove_verify":
    check("selected_point_remove_commit", "c=t['owner']().owned_editor_root.item.curve; assert len(c.curves[0].points)==2; assert t['state']['callbacks']==t['state']['point_calls']+2")
elif stage == "limit":
    run("import struct,time; f=lambda x:struct.unpack('f',struct.pack('f',x))[0]; item=t['owner']().owned_editor_root.item; raw=item['curve']; t['state']['point_timings']=[]\nfor n in (2048,8192,32767):\n points=[{'x':f(i/(2*(n-1))),'y':f(i/(2*(n-1))),'handle':'VECTOR'} for i in range(n-1)]+[{'x':1.0,'y':1.0,'handle':'VECTOR'}]\n start=time.monotonic(); raw['points']=points; constructed=time.monotonic(); item.curve_mapping_sync('curve'); synced=time.monotonic()\n t['state']['point_timings'].append({'points':n,'raw_seconds':constructed-start,'sync_seconds':synced-constructed})\nprint(t['state']['point_timings'])\nt['state']['limit_key']=item.curve.curve_mapping_cache_key(); t['state']['limit_calls']=t['state']['callbacks']")
    open_dialog()
    event('MOUSEMOVE', 'NOTHING', 1050, 280)
    event('LEFTMOUSE', 'PRESS', 1050, 280, ctrl=True)
    event('LEFTMOUSE', 'RELEASE', 1050, 280, ctrl=True)
    click(1050, 366)
    shot("maximum_points_insertions_rejected")
    apply()
    check("both_pointer_insertion_paths_at_32767_points", "c=t['owner']().owned_editor_root.item.curve; assert len(c.curves[0].points)==32767; assert c.curve_mapping_cache_key()==t['state']['limit_key']; assert t['state']['callbacks']==t['state']['limit_calls']")
elif stage == "clipboard":
    run("c=t['owner']().owned_editor_root.item.curve; c.use_clip=True; c.extend='EXTRAPOLATED'; c.clip_max_y=1; c.curves[0].points[-1].location.y=0.625; t['state']['clipboard_calls']=t['state']['callbacks']")
    open_dialog()
    event('MOUSEMOVE', 'NOTHING', 900, 300)
    key('C', ctrl=True, x=900, y=300)
    click(700, 448)
    event('MOUSEMOVE', 'NOTHING', 900, 300)
    key('V', ctrl=True, x=900, y=300)
    shot("scalar_paste_working")
    apply()
    check("scalar_clipboard_roundtrip_noop", "c=t['owner']().owned_editor_root.item.curve; assert c.curves[0].points[-1].location.y==0.625; assert t['state']['callbacks']==t['state']['clipboard_calls']")
    run("t['owner']().owned_editor_root.item.curve.curves[0].points[-1].location.y=0.375; t['state']['clipboard_calls']=t['state']['callbacks']")
    open_dialog()
    event('MOUSEMOVE', 'NOTHING', 900, 300)
    key('V', ctrl=True, x=900, y=300)
    apply()
    check("scalar_clipboard_commits_once", "c=t['owner']().owned_editor_root.item.curve; assert c.curves[0].points[-1].location.y==0.625; assert t['state']['callbacks']==t['state']['clipboard_calls']+1")
elif stage == "rgb_clipboard":
    click(590, 275)
    event('MOUSEMOVE', 'NOTHING', 800, 150)
    key('C', ctrl=True, x=800, y=150)
    run("m=t['native_clipboard_node'].mapping; [setattr(c.points[-1].location, 'y', 0.875) for c in m.curves]; m.update()")
    key('V', ctrl=True, x=800, y=150)
    check("rgb_clipboard_source_verified_by_native_paste", "assert all(c.points[-1].location.y==0.25 for c in t['native_clipboard_node'].mapping.curves)")
    key('ESC', x=800, y=150)
    run("t['state']['clipboard_calls']=t['state']['callbacks']")
    open_dialog()
    click(700, 448)
    event('MOUSEMOVE', 'NOTHING', 900, 300)
    key('V', ctrl=True, x=900, y=300)
    shot("rgb_paste_rejected")
    apply()
    check("rgb_clipboard_rejected_without_replacing_working_curve", "c=t['owner']().owned_editor_root.item.curve; assert c.curves[0].points[-1].location.y==1; assert t['state']['callbacks']==t['state']['clipboard_calls']+1")
elif stage == "callback_delete":
    run("t['state']['owner']='BRUSH'; t['owner']().curve_mapping_initialize(t['state']['path']); t['redraw']()")
    open_dialog()
    click(845, 448)
    run("t['state']['callback_behavior']='delete_owner'")
    apply()
    check("apply_callback_deletes_owner", "assert bpy.data.brushes.get('OwnedEditorBrush') is None; assert t['state']['owner']=='SCENE'")
    run("t['state']['callback_behavior']=None; t['redraw']()")
elif stage == "asset":
    number(1070, 222, 0.75)
    check("external_asset_dialog_staged", "b=t['owner'](); assert b.owned_editor_root.item.curve.curves[0].points[-1].location.y==0.375; assert not b.has_unsaved_changes")
    shot("external_asset_working_075")
    apply()
    check("external_asset_dialog_dirty_actual_owner_once", "b=t['owner'](); assert b.owned_editor_root.item.curve.curves[0].points[-1].location.y==0.75; assert b.has_unsaved_changes; assert not bpy.context.tool_settings.sculpt.brush.has_unsaved_changes; assert t['state']['callbacks']==t['state']['asset_calls']+1")
    run("t['asset_old_curve']=t['owner']().owned_editor_root.item.curve; assert bpy.ops.brush.asset_activate(asset_library_type='CUSTOM', asset_library_identifier='OwnedEditorAssets', relative_asset_identifier='Saved/Brushes/OwnedEditorBrush.asset.blend/Brush/OwnedEditorBrush')=={'FINISHED'}")
    run("assert bpy.ops.brush.asset_revert()=={'FINISHED'}; t['redraw']()")
    check("external_asset_gui_0375_075_0375_revert", "b=t['owner'](); assert b.owned_editor_root.item.curve.curves[0].points[-1].location.y==0.375; assert not b.has_unsaved_changes")
    run("try:\n t['asset_old_curve'].curve_mapping_cache_key()\nexcept ReferenceError:\n t['state'].setdefault('checks',[]).append('external_asset_revert_invalidates_dialog_curve')\nelse:\n raise AssertionError('Revert kept old handle')")
    shot("external_asset_reverted_0375")
elif stage == "asset_verify":
    run("try:\n t['asset_old_curve'].curve_mapping_cache_key()\nexcept ReferenceError:\n t['state'].setdefault('checks',[]).append('external_asset_revert_invalidates_dialog_curve')\nelse:\n raise AssertionError('Revert kept old handle')")
    shot("external_asset_reverted_0375")
elif stage in {"concurrent", "concurrent_finish"}:
    if stage == "concurrent":
        run("bpy.ops.object.mode_set(mode='OBJECT'); t['state']['owner']='SCENE'; c=t['owner']().owned_editor_root.item.curve; c.curves[0].points[-1].location.y=0.375; t['state']['concurrent_calls']=t['state']['callbacks']; t['redraw']()")
        open_dialog()
        click(840, 448)
        run("assert bpy.ops.wm.window_new()=={'FINISHED'}; t['state']['window_index']=1")
        time.sleep(1)
        run("assert len(bpy.context.window_manager.windows)==2; a=bpy.context.window_manager.windows[1].screen.areas[0]; a.spaces.active.show_region_ui=True; a.tag_redraw()")
    click(1025, 145)
    click(750, 480)
    click(1115, 448)
    run("t['state']['window_index']=0")
    apply()
    check("first_of_two_dialogs_commits", "assert t['state']['callbacks']==t['state']['concurrent_calls']+1; t['state']['concurrent_key']=t['owner']().owned_editor_root.item.curve.curve_mapping_cache_key()")
    run("t['state']['window_index']=1")
    apply()
    check("second_concurrent_dialog_rejects_stale_revision", "assert t['owner']().owned_editor_root.item.curve.curve_mapping_cache_key()==t['state']['concurrent_key']; assert t['state']['callbacks']==t['state']['concurrent_calls']+1")
    run("with bpy.context.temp_override(window=bpy.context.window_manager.windows[1]):\n bpy.ops.screen.screenshot(filepath={!r})\n bpy.ops.wm.window_close()".format(str(OUTPUT / "concurrent_stale_rejected.png")))
    run("t['state']['window_index']=0; assert bpy.ops.ui.owned_curve_edit('EXEC_DEFAULT')=={'CANCELLED'}")
elif stage == "callback_unregister":
    open_dialog()
    click(700, 448)
    run("t['state']['callback_behavior']='unregister'")
    apply()
    check("apply_callback_removes_declaration", "assert t['state']['declaration_removed']; assert 'curve' not in t['owner'].__globals__['OwnedEditorItem'].bl_rna.properties")
    shot("callback_unregistered")
elif stage == "unregister_verify":
    check("apply_callback_removes_declaration", "assert t['state']['declaration_removed']; assert 'curve' not in t['owner'].__globals__['OwnedEditorItem'].bl_rna.properties")
    shot("callback_unregistered")
else:
    raise ValueError(stage)
