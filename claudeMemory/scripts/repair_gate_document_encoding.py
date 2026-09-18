# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Normalize newly appended Windows-encoded punctuation without changing existing UTF-8."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for relative in ("README.md", "plans/generic-brush-properties-tasks.md",
                 "codebase/generic-brush-plan2-evidence.md"):
    path = root / relative
    text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    text = "".join(bytes([ord(c) - 0xDC00]).decode("cp1252")
                   if 0xDC80 <= ord(c) <= 0xDCFF else c for c in text)
    path.write_text(text.replace("\r", ""), encoding="utf-8", newline="\n")
path = root / "scripts/record_owned_curve_gate.py"
text = path.read_text(encoding="utf-8").replace(".read_text()", '.read_text(encoding="utf-8")')
text = text.replace("path.write_text(text)", 'path.write_text(text, encoding="utf-8")')
text = text.replace('path.write_text(text[:start] + section + text[end:])',
                    'path.write_text(text[:start] + section + text[end:], encoding="utf-8")')
path.write_text(text, encoding="utf-8")
