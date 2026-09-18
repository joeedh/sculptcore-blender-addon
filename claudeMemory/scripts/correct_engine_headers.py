# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Remove addon license headers introduced into engine work; preserve preexisting notices."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
engine = root / 'engine'


def git(*args):
    return subprocess.check_output(['git', '-C', str(engine), *args])


paths = set(git('diff', '--name-only', '-z', 'HEAD').split(b'\0'))
paths.update(git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))
records = []
preserved = []
for raw in sorted(paths):
    if not raw:
        continue
    relative = raw.decode('utf-8')
    path = engine / relative
    if not path.is_file():
        continue
    original = path.read_bytes()
    if b'SPDX-FileCopyrightText: 2026 Blender Authors' not in original[:256]:
        continue
    previous = subprocess.run(['git', '-C', str(engine), 'show', 'HEAD:' + relative],
                              capture_output=True)
    if b'SPDX-FileCopyrightText: 2026 Blender Authors' in previous.stdout[:256]:
        preserved.append(relative)
        continue
    if original.startswith(b'/* SPDX-FileCopyrightText:'):
        match = re.match(rb'/\* SPDX-FileCopyrightText: 2026 Blender Authors\r?\n'
                         rb'(?: \*\r?\n)? \* SPDX-License-Identifier: GPL-2\.0-or-later \*/'
                         rb'\r?\n(?:\r?\n)?', original)
    else:
        match = re.match(rb'(?P<prefix>\#|//) SPDX-FileCopyrightText: 2026 Blender Authors\r?\n'
                         rb'(?P=prefix) SPDX-License-Identifier: GPL-2\.0-or-later\r?\n'
                         rb'(?:\r?\n)?', original)
    assert match, relative
    corrected = original[match.end():]
    path.write_bytes(corrected)
    assert path.read_bytes() == corrected
    assert original == match.group() + corrected
    records.append(dict(path=relative, removed_header=match.group().decode('utf-8'),
                        before_sha256=hashlib.sha256(original).hexdigest(),
                        after_sha256=hashlib.sha256(corrected).hexdigest()))

result = dict(changed=records, preexisting_notices_preserved=preserved,
              policy='Engine LICENSE.txt and existing header-free source conventions; addon rule is scoped.')
(root / 'claudeMemory/tests/engine-header-correction.json').write_text(
    json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('ENGINE_HEADER_CORRECTION_PASS', len(records), 'introduced headers removed')
