# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Smoke-test a *packaged* SculptBlender build: does its native half load?

Run headless against an extracted release archive — see
``.github/workflows/smoke-test-packages.yml``::

    blender --background --factory-startup --python tools/smoke_test_package.py

``tools/verify_addon.py`` answers "did the add-on come up enabled?".  This
answers the question a package can only fail *away* from the machine that built
it: is ``sculptcore_capi`` — and everything it links — present inside the
package, loadable, and callable?

Each check targets a way a package has broken (or could break) while every
build step stayed green:

* **Live at startup.**  ``Brush.sculptcore`` exists only if
  ``engine_props.register()`` walked the kernel manifests through the DLL at
  startup; its failure path is a ``print``, not an exception, so the add-on
  reports itself enabled either way.
* **Vendored, not borrowed.**  The ``sculptcore`` ctypes package and every
  engine shared library the process actually mapped must live inside the
  add-on's ``lib/sculptcore/``.  A library satisfied from elsewhere on the test
  machine — a build-machine path that happens to exist, a system OpenMP
  runtime — is exactly the bug ``fetch-blender-dist.mjs``'s ``fixLibLinkage()``
  exists to prevent, and it is invisible wherever the libs were built.
* **Registrable.**  The engine provider's external-draw ABI version must match
  the one this Blender expects.  A skewed fork/engine pair fails nothing else:
  registration is refused silently and the viewport draws fallback geometry.
* **Complete.**  Every kernel the brush table names must be in the engine's
  enum.  A package whose libs were built without this repo's ``brushes/*.sbrush``
  (``--kernels-extra``) is missing ``NUDGE`` and nothing else notices.
* **Callable.**  A mesh round-trips through the c-api, so native code is proven
  to *run*, not merely to load.

Nothing here needs a GPU, a window, or any tool installed on the test machine.
"""

import os
import sys
import traceback

import bpy

MODULE = "sculptcore_addon"

# Loaded modules that must come out of the package, matched on basename prefix:
# the engine's own libraries, plus the LLVM OpenMP runtime it is built against
# (`libomp`, since the engine is a clang build on every platform). One of these
# resolved from the test machine means the package only runs where a compatible
# copy happens to be installed.
STRICT_LIB_PREFIXES = ("sculptcore_capi", "libsculptcore_capi",
                       "wgpu_native", "libwgpu_native", "libomp")

# The other OpenMP runtimes: GNU's, which Blender's own stack pulls in (its
# bundled numpy's OpenBLAS links it), and MSVC's, which its Windows deps may.
# Worth reporting — the engine is not supposed to be reaching for either — but
# not the engine's, so not a failure.
SOFT_LIB_PREFIXES = ("libgomp", "vcomp")

failures = []
warnings = []


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


def loaded_module_paths():
    """Absolute paths of every shared library mapped into this process, or
    None on a platform we cannot enumerate."""
    import ctypes

    if sys.platform == "linux":
        paths = []
        with open("/proc/self/maps", "r") as fh:
            for line in fh:
                path = line.rstrip("\n").partition(" /")[2]
                if path:
                    paths.append("/" + path)
        return sorted(set(paths))

    if sys.platform == "darwin":
        libc = ctypes.CDLL(None)
        libc._dyld_image_count.restype = ctypes.c_uint32
        libc._dyld_get_image_name.restype = ctypes.c_char_p
        libc._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        return [libc._dyld_get_image_name(i).decode("utf-8", "replace")
                for i in range(libc._dyld_image_count())]

    if sys.platform == "win32":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.EnumProcessModules.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong)]
        psapi.GetModuleFileNameExW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
        proc = k32.GetCurrentProcess()
        # Two passes: the first sizes the array, since a Blender process maps
        # far more than a fixed guess would hold.
        needed = ctypes.c_ulong()
        if not psapi.EnumProcessModules(proc, None, 0, ctypes.byref(needed)):
            return None
        count = needed.value // ctypes.sizeof(ctypes.c_void_p)
        mods = (ctypes.c_void_p * count)()
        if not psapi.EnumProcessModules(proc, mods, ctypes.sizeof(mods), ctypes.byref(needed)):
            return None
        buf = ctypes.create_unicode_buffer(32768)
        paths = []
        for i in range(min(count, needed.value // ctypes.sizeof(ctypes.c_void_p))):
            if psapi.GetModuleFileNameExW(proc, mods[i], buf, len(buf)):
                paths.append(buf.value)
        return paths

    return None


def is_inside(path, directory):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(directory)]) \
            == os.path.realpath(directory)
    except ValueError:
        # Different drives on Windows — definitively not inside.
        return False


def check_environment():
    """The developer overrides must be absent, or the run tests a checkout on
    this machine rather than the package that was downloaded."""
    for var in ("SCULPTCORE_PYTHON_PATH", "SCULPTCORE_CAPI_PATH"):
        if os.environ.get(var):
            fail("{:s} is set ({!r}); the package's own runtime is not what would be "
                 "tested".format(var, os.environ[var]))


def check_draw_provider(capi):
    """The external draw provider is registrable against this Blender.

    A package whose engine and Blender were built against different
    external-draw ABI versions still passes every other check here: the fork
    silently rejects the provider at registration (the RNA string setter cannot
    report), and the mode then draws the flush-to-Mesh fallback — for multires,
    the base cage. The provider struct leads with its ``abi_version``; Blender
    exposes the version it expects as the ``bl_draw_provider_abi_version``
    property default, readable without a mode instance."""
    import ctypes

    provider = capi.lib.sc_external_draw_provider()
    if not provider:
        fail("sc_external_draw_provider() returned null — the mode has no draw provider "
             "to register")
        return
    engine_abi = ctypes.cast(ctypes.c_void_p(provider),
                             ctypes.POINTER(ctypes.c_int)).contents.value
    abi_prop = bpy.types.ObjectModeType.bl_rna.properties.get("bl_draw_provider_abi_version")
    if abi_prop is None:
        fail("this Blender's ObjectModeType has no bl_draw_provider_abi_version — it "
             "predates the external-draw ABI the engine was built for; the provider is "
             "silently rejected and the viewport draws fallback geometry")
        return
    if abi_prop.default != engine_abi:
        fail("external-draw ABI skew: the engine's provider reports v{:d} but this Blender "
             "expects v{:d}; registration is silently refused and the viewport draws "
             "fallback geometry (repackage with matching fork/engine builds)".format(
                 engine_abi, abi_prop.default))


def check_startup_engine():
    """The engine was reachable during the add-on's own registration.

    ``Brush.sculptcore`` is generated from the kernel uniform manifests, which
    are read through the DLL — so its presence proves the native library loaded
    at startup, in the ordinary launch path, with nothing forcing it."""
    if not hasattr(bpy.types.Brush, "sculptcore"):
        fail("Brush.sculptcore is missing — engine_props.register() could not reach the "
             "engine at startup (it fails silently); see the console for its message")


def main():
    check_environment()
    check_startup_engine()

    import sculptcore_addon
    from sculptcore_addon import engine, mapping

    addon_dir = os.path.dirname(os.path.abspath(sculptcore_addon.__file__))
    lib_dir = os.path.join(addon_dir, "lib", "sculptcore")
    if not os.path.isdir(lib_dir):
        fail("the add-on carries no vendored runtime at {:s}".format(lib_dir))

    # Force the load explicitly (rather than relying on startup having done it),
    # so an engine failure surfaces here as a traceback instead of a missing
    # feature. capi() additionally binds every c-api entry point the conversion
    # layer calls, which fails loudly on a library missing an export.
    manager = engine.manager()
    capi = engine.capi()
    check_draw_provider(capi)

    import sculptcore
    pkg_file = os.path.abspath(sculptcore.__file__)
    if not is_inside(pkg_file, lib_dir):
        fail("the `sculptcore` ctypes package was imported from {:s}, outside the "
             "package's vendored lib/".format(pkg_file))

    # --- the native libraries -----------------------------------------------
    # `commonpath` of the executable and the add-on is the package root on every
    # layout: the bin tree on Windows/Linux, Blender.app on macOS.
    package_root = os.path.dirname(bpy.app.binary_path)
    try:
        package_root = os.path.commonpath([os.path.realpath(bpy.app.binary_path),
                                           os.path.realpath(addon_dir)])
    except ValueError:
        pass

    modules = loaded_module_paths()
    if modules is None:
        warn("cannot enumerate loaded modules on {:s}; the engine libraries were not "
             "checked for provenance".format(sys.platform))
    else:
        strict = [p for p in modules
                  if os.path.basename(p).lower().startswith(STRICT_LIB_PREFIXES)]
        soft = [p for p in modules
                if os.path.basename(p).lower().startswith(SOFT_LIB_PREFIXES)]
        print("smoke: engine-side libraries mapped into the process:")
        for path in sorted(strict + soft):
            print("  {:s}{:s}".format(
                path, "" if is_inside(path, lib_dir) else "   <-- outside the add-on's lib/"))

        if not [p for p in strict if "sculptcore_capi" in os.path.basename(p).lower()]:
            fail("no sculptcore_capi library is mapped into the process, yet the engine "
                 "reported itself loaded")
        if not [p for p in strict if "wgpu_native" in os.path.basename(p).lower()]:
            warn("wgpu_native is not mapped; the engine loaded without it (headless), so "
                 "its packaging was not exercised")
        for path in strict:
            if not is_inside(path, lib_dir):
                where = "elsewhere in the package" if is_inside(path, package_root) else "this machine"
                fail("engine library {:s} was loaded from {:s} ({:s}) — it must be vendored "
                     "into {:s}, or the package only runs on a machine that already has a "
                     "copy".format(os.path.basename(path), path, where, lib_dir))
        for path in soft:
            if not is_inside(path, lib_dir):
                warn("{:s} was loaded from {:s}; the engine is not expected to reach for a "
                     "non-LLVM OpenMP runtime".format(os.path.basename(path), path))

    # --- the kernels --------------------------------------------------------
    # Missing kernels are how libs built without this repo's brushes/ (the
    # engine's `--kernels-extra`) show up: the brush is present in the UI and
    # every stroke with it silently cancels.
    items = manager.get("sculptcore::brush::SculptBrushes").items
    missing = sorted({k for k in mapping.KERNEL_BY_TYPE.values() if items.get(k) is None})
    if missing:
        fail("kernels missing from the engine enum: {:s} (libs built without "
             "`--kernels-extra ../brushes`?)".format(", ".join(missing)))

    # --- native code actually runs ------------------------------------------
    import ctypes

    import numpy as np

    lib = capi.lib
    positions = np.array([0, 0, 0, 1, 0, 0, 0, 1, 0], dtype=np.float32)
    corner_verts = np.array([0, 1, 2], dtype=np.int32)
    face_offsets = np.array([0, 3], dtype=np.int32)
    mesh_ptr = lib.Mesh_fromArrays(positions, 3, corner_verts, 3, face_offsets, 1)
    if not mesh_ptr:
        fail("Mesh_fromArrays rejected a one-triangle mesh")
        return
    tree_ptr = 0
    try:
        nv, nc, nf, cap = (ctypes.c_int(0) for _ in range(4))
        lib.Mesh_arraySizes(mesh_ptr, ctypes.byref(nv), ctypes.byref(nc),
                            ctypes.byref(nf), ctypes.byref(cap))
        if (nv.value, nc.value, nf.value) != (3, 3, 1):
            fail("engine round trip returned {:d} verts / {:d} corners / {:d} faces, "
                 "expected 3 / 3 / 1".format(nv.value, nc.value, nf.value))
        out_pos = np.empty(nv.value * 3, dtype=np.float32)
        out_corners = np.empty(nc.value, dtype=np.int32)
        out_offsets = np.empty(nf.value + 1, dtype=np.int32)
        vert_map = np.empty(max(cap.value, 1), dtype=np.int32)
        lib.Mesh_toArrays(mesh_ptr, out_pos, out_corners, out_offsets, vert_map)
        if not np.array_equal(out_pos, positions):
            fail("engine round trip changed the vertex positions: {!r}".format(out_pos))
        # The spatial tree is what every stroke sculpts through, and the one
        # engine subsystem heavy enough to notice a half-linked library.
        tree_ptr = lib.Mesh_buildSpatialTree(mesh_ptr, 0, 0, 0)
        if not tree_ptr:
            fail("Mesh_buildSpatialTree failed on a one-triangle mesh")
    finally:
        if tree_ptr:
            lib.SpatialTree_free(tree_ptr)
        lib.freeMesh(mesh_ptr)

    print("smoke: blender {:s}, all {:d} mapped kernels present, c-api round trip ok".format(
        bpy.app.version_string, len(mapping.KERNEL_BY_TYPE)))


try:
    main()
except Exception:
    traceback.print_exc()
    fail("an exception escaped the smoke test (above)")

for msg in warnings:
    sys.stderr.write("smoke_test_package: warning: {:s}\n".format(msg))

if failures:
    for msg in failures:
        sys.stderr.write("smoke_test_package: FAILED: {:s}\n".format(msg))
    sys.exit(1)

print("smoke_test_package: the packaged SculptCore engine loads, is self-contained, "
      "and runs")
