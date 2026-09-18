# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed generic event input API into the companion fork."""

from pathlib import Path
import re

root = Path('C:/dev/blender/main')
updates = {}


def edit(name, old, new, count=1):
    path = root / name
    text = updates.get(path, path.read_text(encoding='utf-8'))
    actual = text.count(old)
    if actual != count:
        raise RuntimeError('{}: expected {} matches, got {}: {!r}'.format(name, count, actual, old[:90]))
    updates[path] = text.replace(old, new)


types = 'intern/ghost/GHOST_Types.hh'
edit(types, 'struct GHOST_TabletData {', '''enum GHOST_TTabletInput : uint8_t {
  GHOST_kTabletPressure = 1 << 0,
  GHOST_kTabletTiltX = 1 << 1,
  GHOST_kTabletTiltY = 1 << 2,
};

struct GHOST_TabletData {''')
edit(types, '  float Ytilt;              /* range -1.0 (away from user) to +1.0 (toward user) */',
     '''  float Ytilt;              /* range -1.0 (away from user) to +1.0 (toward user) */
  /** Channels whose current values the device producer has established. */
  uint8_t InputPresence = 0;''')
edit(types, '  GHOST_TabletData tablet;\n};', '''  GHOST_TabletData tablet;
  /** True only for an audited acquisition timestamp, not dispatch/warp time. */
  bool time_is_input = false;
  bool is_input_sample = true;
};''', count=2)
for kind, arg in (('Cursor', 'x, y'), ('Button', 'button')):
    path = 'intern/ghost/intern/GHOST_Event{}.hh'.format(kind)
    edit(path, 'const GHOST_TabletData &tablet)', '''const GHOST_TabletData &tablet,
                    bool time_is_input = false,
                    bool is_input_sample = true)''')
    edit(path, '{{{}, tablet}}'.format(arg), '{{{}, tablet, time_is_input, is_input_sample}}'.format(arg))

win = 'intern/ghost/intern/GHOST_WindowWin32.cc'
edit(win, '    outPointerInfo[i].tabletData.Active = GHOST_kTabletModeStylus;',
     '    outPointerInfo[i].tabletData = GHOST_TABLET_DATA_NONE;\n    outPointerInfo[i].tabletData.Active = GHOST_kTabletModeStylus;')
for flag, channel in (('PRESSURE', 'Pressure'), ('TILT_X', 'TiltX'), ('TILT_Y', 'TiltY')):
    old = '    if (pointerPenInfo[i].penMask & PEN_MASK_{}) {{'.format(flag)
    edit(win, old, old + '\n      outPointerInfo[i].tabletData.InputPresence |= GHOST_kTablet{};'.format(channel))
wintab = 'intern/ghost/intern/GHOST_Wintab.cc'
edit(wintab, '    GHOST_WintabInfoWin32 out;',
     '    GHOST_WintabInfoWin32 out;\n    out.tabletData = GHOST_TABLET_DATA_NONE;')
edit(wintab, '    if (max_pressure_ > 0) {',
     '    if (max_pressure_ > 0) {\n      out.tabletData.InputPresence |= GHOST_kTabletPressure;')
edit(wintab, '    if ((max_azimuth_ > 0) && (max_altitude_ > 0)) {',
     '    if ((max_azimuth_ > 0) && (max_altitude_ > 0)) {\n      out.tabletData.InputPresence |= GHOST_kTabletTiltX | GHOST_kTabletTiltY;')
system = 'intern/ghost/intern/GHOST_SystemWin32.cc'
edit(system, 'static uint64_t getMessageTime(GHOST_SystemWin32 *system)\n{', '''static uint64_t inputTickTime(GHOST_SystemWin32 *system, uint32_t tick)
{
  /* Input packets are at most one 32-bit tick period behind the current clock. */
  const uint32_t age = uint32_t(GetTickCount()) - tick;
  const uint64_t now = system->getMilliSeconds();
  return now >= age ? now - age : 0;
}

static uint64_t getMessageTime(GHOST_SystemWin32 *system)
{''')
edit(system, '  for (GHOST_WintabInfoWin32 &info : wintabInfo) {',
     '  for (GHOST_WintabInfoWin32 &info : wintabInfo) {\n    info.time = inputTickTime(system, uint32_t(info.time));')
path = root / system
text = updates[path]
pattern = r'(std::make_unique<GHOST_Event(?:Cursor|Button)>\([\s\S]*?)(\);|\)\);)'
matches = list(re.finditer(pattern, text))
if len(matches) != 12:
    raise RuntimeError('Unexpected Windows cursor/button producer count: {}'.format(len(matches)))
text = re.sub(pattern, lambda m: m[1] + ', true' + m[2], text)
updates[path] = text
cocoa = 'intern/ghost/intern/GHOST_SystemCocoa.mm'
edit(cocoa, 'getMilliSeconds(), GHOST_kEventCursorMove, window, x, y, window->GetCocoaTabletData()));',
     'getMilliSeconds(), GHOST_kEventCursorMove, window, x, y, window->GetCocoaTabletData(), false, false));')

wmtypes = 'source/blender/windowmanager/WM_types.hh'
edit(wmtypes, '  char is_motion_absolute;\n};', '''  char is_motion_absolute;
  /** Pressure, tilt-X and tilt-Y validity bits, matching GHOST_TTabletInput. */
  uint8_t input_presence = 0;
};''')
edit(wmtypes, 'struct wmEvent {\n  wmEvent *next, *prev;', '''struct wmEvent {
  wmEvent *next, *prev;

  /** Event-owned monotonic seconds. Never copied into persistent eventstate. */
  double input_time = 0.0;
  bool has_input_time = false;
  /** Distinguishes real/simulated input from redraw-generated mouse motion. */
  bool is_input_sample = false;''')
wmevents = 'source/blender/windowmanager/intern/wm_event_system.cc'
edit(wmevents, '    wmtab->active = int(tablet_data->Active);',
     '    wmtab->active = int(tablet_data->Active);\n    wmtab->input_presence = tablet_data->InputPresence;')
edit(wmevents, '  event = *event_state;\n  event.flag',
     '  event = *event_state;\n  event.input_time = 0.0;\n  event.has_input_time = false;\n  event.is_input_sample = false;\n  event.flag')
for prefix in ('cd', 'bd'):
    old = '      wm_tablet_data_from_ghost(&{}->tablet, &event.tablet);'.format(prefix)
    edit(wmevents, old, old + '''
      event.input_time = {}->time_is_input ? double(event_time_ms) / 1000.0 : 0.0;
      event.has_input_time = {}->time_is_input;
      event.is_input_sample = {}->is_input_sample;'''.format(prefix, prefix, prefix))
edit(wmevents, '        wmEvent event_other = *win_other->runtime->eventstate;', '''        wmEvent event_other = *win_other->runtime->eventstate;
        event_other.input_time = event.input_time;
        event_other.has_input_time = event.has_input_time;
        event_other.is_input_sample = event.is_input_sample;
        event_other.tablet = event.tablet;''', count=2)
edit(wmevents, '      wmEvent tevent = *(win.runtime->eventstate);', '''      wmEvent tevent = *(win.runtime->eventstate);
      tevent.input_time = 0.0;
      tevent.has_input_time = false;
      tevent.is_input_sample = false;''')
edit(wmevents, '  tevent.type = MOUSEMOVE;\n  tevent.val = KM_NOTHING;', '''  tevent.input_time = 0.0;
  tevent.has_input_time = false;
  tevent.is_input_sample = false;
  tevent.type = MOUSEMOVE;
  tevent.val = KM_NOTHING;''')
edit(wmevents, 'static wmEvent *wm_event_add_mousemove(wmWindow *win, const wmEvent *event)\n{', '''void WM_event_retire_mousemove(wmEvent *event)
{
  if (event && event->type == MOUSEMOVE) {
    event->type = INBETWEEN_MOUSEMOVE;
    event->flag = eWM_EventFlag(0);
  }
}

static wmEvent *wm_event_add_mousemove(wmWindow *win, const wmEvent *event)
{''')
edit(wmevents, '''  if (event_last && event_last->type == MOUSEMOVE) {
    event_last->type = INBETWEEN_MOUSEMOVE;
    event_last->flag = eWM_EventFlag(0);
  }''', '  WM_event_retire_mousemove(event_last);')
edit('source/blender/windowmanager/WM_api.hh',
     'wmEvent *WM_event_add_simulate(wmWindow *win, const wmEvent *event_to_add);',
     'wmEvent *WM_event_add_simulate(wmWindow *win, const wmEvent *event_to_add);\n/** Retype a preceding queued mouse move while preserving its input sample. */\nvoid WM_event_retire_mousemove(wmEvent *event);')
edit('source/blender/makesrna/intern/rna_wm_api.cc',
     '  wmEvent e = *win->runtime->eventstate;', '''  wmEvent e = *win->runtime->eventstate;
  e.input_time = 0.0;
  e.has_input_time = false;
  e.is_input_sample = ISMOUSE_MOTION(type) || ISMOUSE_BUTTON(type);''')

rna = 'source/blender/makesrna/intern/rna_wm.cc'
getters = '''static bool rna_Event_has_time_get(PointerRNA *ptr)
{
  return static_cast<const wmEvent *>(ptr->data)->has_input_time;
}

static bool rna_Event_is_input_sample_get(PointerRNA *ptr)
{
  return static_cast<const wmEvent *>(ptr->data)->is_input_sample;
}

'''
for name, bit in (('pressure', 1), ('tilt_x', 2), ('tilt_y', 4)):
    mouse = 'event->tablet.active == EVT_TABLET_NONE || ' if name == 'pressure' else ''
    getters += '''static bool rna_Event_has_%s_get(PointerRNA *ptr)
{
  const wmEvent *event = static_cast<const wmEvent *>(ptr->data);
  return %s(event->tablet.input_presence & %d) != 0;
}

''' % (name, mouse, bit)
edit(rna, 'static float rna_Event_pressure_get(PointerRNA *ptr)', getters + 'static float rna_Event_pressure_get(PointerRNA *ptr)')
properties = ''
for name, label in (('has_time', 'Has Acquisition Time'), ('is_input_sample', 'Is Input Sample'),
                    ('has_pressure', 'Has Pressure'), ('has_tilt_x', 'Has Tilt X'), ('has_tilt_y', 'Has Tilt Y')):
    properties += '''  prop = RNA_def_property(srna, "%s", PROP_BOOLEAN, PROP_NONE);
  RNA_def_property_clear_flag(prop, PROP_EDITABLE);
  RNA_def_property_boolean_funcs(prop, "rna_Event_%s_get", nullptr);
  RNA_def_property_ui_text(prop, "%s", "Input availability for this event");

''' % (name, name, label)
edit(rna, '  prop = RNA_def_property(srna, "pressure", PROP_FLOAT, PROP_FACTOR);',
     properties + '  prop = RNA_def_property(srna, "pressure", PROP_FLOAT, PROP_FACTOR);')

# Finish all exact-match checks before writing any file.
for path, text in updates.items():
    path.write_text(text, encoding='utf-8', newline='\n')
print('Updated {} event acquisition files'.format(len(updates)))
