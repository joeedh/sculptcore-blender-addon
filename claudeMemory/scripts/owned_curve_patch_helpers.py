# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exact patch helpers for the already-installed owned RNA layer."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT.parent / "main"
RNA = FORK / "source/blender/makesrna"
PY = FORK / "source/blender/python/intern"
bpy = PY / "bpy_rna.cc"
props = PY / "bpy_props.cc"
color = RNA / "intern/rna_color.cc"
access = RNA / "intern/rna_access.cc"


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    assert text.count(old) == 1, (path.name, old, text.count(old))
    path.write_text(text.replace(old, new), newline="\n")


def function_text(path, function, transform):
    text = path.read_text()
    match = re.search(r"(?m)^[\w :*&]+\b" + function + r"\([^;]*?\)\n\{", text)
    assert match, function
    end = text.find("\n}\n", match.end()) + 3
    path.write_text(text[:match.start()] + transform(text[match.start():end]).rstrip() + "\n\n" + text[end:], newline="\n")


def start(path, function, code):
    function_text(path, function, lambda body: body if code in body else body.replace("\n{", "\n{\n" + code, 1))


for source, destination in (
    ("RNA_owned_curve.hh", RNA / "RNA_owned_curve.hh"),
    ("rna_owned_curve.cc", RNA / "intern/rna_owned_curve.cc"),
):
    destination.write_bytes((ROOT / "claudeMemory/implementation" / source).read_bytes())
