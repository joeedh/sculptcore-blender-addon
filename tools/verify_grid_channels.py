# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate the grid channel c-api (plans/grid-domain-attributes.md, B1).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_grid_channels.py -- [--verbose]

What is checked
---------------
``subdiv/c-api/grid_channel_c_api.h`` is the whole interface an embedding host
has to a multires-domain attribute: enumerate the store's channels, describe
one, and read or write a level of it a grid range at a time. Blender is the
host that mostly *cannot* store them, which is why the c-api has to be graded
from outside the engine anyway — the addon is the only place it is crossed
through ctypes, and a c-api function left out of ``wasm_add_symbols`` compiles
and links cleanly and is simply invisible at runtime.

So the gates are a host's own sequence:

1. every export resolves and the store describes itself — channel 0 is
   ``disp``, persistent and the one Delta channel;
2. a *persistent* Authored channel can be declared, which is the state P4 could
   not express (``gridAttrEnsureChannel`` hardcoded ``persist = false``), and
   the two flags are set independently — a session channel is Authored too;
3. an Authored level nothing has written reads back as zeros *without*
   allocating storage, so asking what is there costs nothing;
4. a level written through the c-api reads back byte-identical, whole or one
   grid at a time, and an out-of-range grid or an undersized buffer is refused
   rather than overrunning;
5. subdivide + delete-higher is the identity on that channel. This is the point
   of the whole level-rule axis: before it, ``persist`` decided seeding, so an
   authored layer either blanked on subdivide or was lost on delete-higher.

What renders is not checked here: a painted grid channel needs a viewport, and
giving multires colour a durable home in ``ob.data`` is B2a's job, not B1's.
"""

import sys

import ctypes
import bpy
import numpy as np

from sculptcore_addon import convert, engine

VERBOSE = False
FAILURES = []

# GridElemDomain / mesh::AttrType / GridLevelRule, mirrored from the engine.
DOMAIN_VERTEX = 0
ATTR_FLOAT4 = 4
RULE_DELTA = 0
RULE_AUTHORED = 1


def check(condition, message):
    if condition:
        if VERBOSE:
            print("  ok   {:s}".format(message))
    else:
        FAILURES.append(message)
        print("  FAIL {:s}".format(message))


def _object(name, n, level):
    """An n x n quad cage under a MULTIRES modifier — every cage face is a quad,
    so the store holds exactly four grids per face."""
    verts = [(float(x), float(y), 0.0) for y in range(n + 1) for x in range(n + 1)]
    w = n + 1
    faces = [(y * w + x, y * w + x + 1, (y + 1) * w + x + 1, (y + 1) * w + x)
             for y in range(n) for x in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    md = ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(level):
        bpy.ops.object.multires_subdivide(modifier=md.name)
    return ob


def _name(lib, mr, index):
    buf = ctypes.create_string_buffer(256)
    if lib.Multires_gridChannelName(mr, index, buf, len(buf)) < 0:
        return None
    return buf.value.decode("utf-8")


def _info(lib, mr, channel):
    out = [ctypes.c_int(-1) for _ in range(5)]
    if not lib.Multires_gridChannelInfo(mr, channel, *[ctypes.byref(v) for v in out]):
        return None
    return [v.value for v in out]


def run():
    lib = engine.capi().lib
    ob = _object("chgrid", 2, 2)

    convert.enter(ob)
    session = engine.sessions[ob.name]
    mr = session.multires_ptr
    check(bool(mr), "session carries a multires stack")
    if not mr:
        convert.exit_(ob)
        return

    level = lib.Multires_maxLevel(mr)
    check(level >= 2, "the stack has {:d} levels".format(level))

    # --- 1: enumeration, and disp's own flags ---
    count = lib.Multires_gridChannelCount(mr)
    check(count >= 1, "the store reports {:d} channel(s)".format(count))
    check(_name(lib, mr, 0) == "disp", "channel 0 is disp")
    check(_name(lib, mr, count) is None, "a bad channel index is refused, not read")
    info = _info(lib, mr, 0)
    check(info is not None and info[0] == 3 and info[1] == DOMAIN_VERTEX,
          "disp is 3 floats on the vertex domain")
    check(info is not None and info[3] == 1 and info[4] == RULE_DELTA,
          "disp is persistent and the one Delta channel")

    # --- 2: the two flags are independent ---
    col = lib.Multires_gridChannelEnsure(mr, b"col", 4, DOMAIN_VERTEX, ATTR_FLOAT4,
                                         1, RULE_AUTHORED)
    check(col > 0, "declared a persistent Authored channel")
    check(lib.Multires_gridChannelFind(mr, b"col") == col, "found it back by name")
    info = _info(lib, mr, col)
    check(info is not None and info[3] == 1 and info[4] == RULE_AUTHORED,
          "it reports persist=1, rule=Authored")
    sess = lib.Multires_gridChannelEnsure(mr, b"sess", 4, DOMAIN_VERTEX, ATTR_FLOAT4,
                                          0, RULE_AUTHORED)
    info = _info(lib, mr, sess)
    check(sess > 0 and info is not None and info[3] == 0 and info[4] == RULE_AUTHORED,
          "a session channel is Authored too — the host owns persistence alone")
    check(lib.Multires_gridChannelEnsure(mr, b"col", 2, DOMAIN_VERTEX, ATTR_FLOAT4,
                                         1, RULE_AUTHORED) == -1,
          "re-declaring at another width is refused")
    check(lib.Multires_gridChannelEnsure(mr, b"col", 4, DOMAIN_VERTEX, ATTR_FLOAT4,
                                         1, RULE_AUTHORED) == col,
          "re-declaring it unchanged finds it")

    per_grid = lib.Multires_gridChannelGridFloats(mr, level, col)
    check(per_grid > 0, "one grid holds {:d} floats".format(per_grid))
    grids = lib.Multires_levelSampleCount(mr, level) // (per_grid // 4)
    check(grids == 16, "16 grids (4 cage quads x 4 corners), got {:d}".format(grids))
    total = per_grid * grids

    # --- 3: an untouched Authored level is free to read ---
    check(not lib.Multires_gridChannelLevelAllocated(mr, level, col),
          "the new channel holds nothing at this level")
    values = np.full(total, -1.0, dtype=np.float32)
    check(lib.Multires_gridChannelRead(mr, level, col, 0, grids, values, total) == total,
          "read the whole level back")
    check(not values.any(), "an untouched Authored level reads as zeros")
    check(not lib.Multires_gridChannelLevelAllocated(mr, level, col),
          "and reading it allocated nothing")

    # --- 4: write / read round trip ---
    values = np.arange(total, dtype=np.float32) * 0.5 + 1.0
    check(lib.Multires_gridChannelWrite(mr, level, col, 0, grids, values, total) == total,
          "wrote the whole level")
    check(bool(lib.Multires_gridChannelLevelAllocated(mr, level, col)),
          "the level is allocated now")
    back = np.zeros(total, dtype=np.float32)
    check(lib.Multires_gridChannelRead(mr, level, col, 0, grids, back, total) == total,
          "read it back")
    check(np.array_equal(back, values), "the level round-tripped byte-identical")

    one = np.zeros(per_grid, dtype=np.float32)
    check(lib.Multires_gridChannelRead(mr, level, col, 1, 1, one, per_grid) == per_grid,
          "a single grid is addressable on its own")
    check(np.array_equal(one, values[per_grid:2 * per_grid]),
          "and holds that grid's block")
    check(lib.Multires_gridChannelRead(mr, level, col, grids, 1, one, per_grid) == 0,
          "a grid past the end is refused")
    check(lib.Multires_gridChannelRead(mr, level, col, 0, 1, one, per_grid - 1) == 0,
          "an undersized buffer is refused")

    # --- 5: the level rule is what makes an authored layer durable ---
    lib.Multires_addLevel(mr)
    check(lib.Multires_gridChannelLevelAllocated(mr, level + 1, col),
          "subdivide seeded the new finest level from this one")
    lib.Multires_removeTopLevel(mr)
    back[:] = 0.0
    check(lib.Multires_gridChannelRead(mr, level, col, 0, grids, back, total) == total,
          "read the level after subdivide + delete higher")
    check(np.array_equal(back, values), "and it came back untouched")

    check(lib.Multires_gridChannelRemove(mr, 0) == 0, "disp cannot be removed")
    check(lib.Multires_gridChannelRemove(mr, col) == 1, "an added channel can be")
    check(lib.Multires_gridChannelFind(mr, b"col") == -1, "and is gone")

    convert.exit_(ob)


def main():
    global VERBOSE

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    VERBOSE = "--verbose" in argv
    for arg in argv:
        if arg != "--verbose":
            raise SystemExit("unknown argument {!r}".format(arg))

    from sculptcore_addon import handlers
    handlers.unregister()

    print("grid channel c-api gate")
    run()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
