# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p=Path('C:/dev/blender/main/intern/ghost/intern/GHOST_SystemWayland.cc')
s=p.read_text()
a=s.index('      if (xy_motion_create_event) {')
b=s.index('      if (surface_needs_commit)',a)
part=s[a:b]
assert part.count('GHOST_TABLET_DATA_NONE));')==1
s=s[:a]+part.replace('GHOST_TABLET_DATA_NONE));','GHOST_TABLET_DATA_NONE, false, false));')+s[b:]
p.write_text(s)
