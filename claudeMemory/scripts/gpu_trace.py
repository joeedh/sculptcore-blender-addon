# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""In-process RenderDoc capture control, callable from Blender's own Python.

Blender exposes ``GPU_debug_capture_begin``/``_end`` (``GPU_debug.hh``), but that
path is compiled out unless the build sets ``WITH_RENDERDOC=ON`` and it has no
Python binding, so it cannot drive a scripted A/B. This module talks to
RenderDoc's in-application API directly instead, which needs no fork change at
all: when Blender is launched under ``renderdoccmd capture``, ``renderdoc.dll``
is already hooked into the process, and ``RENDERDOC_GetAPI`` hands back a struct
of function pointers we can drive from ctypes.

Why ``GetModuleHandleW`` and not ``ctypes.WinDLL("renderdoc.dll")``: ``WinDLL``
goes through ``LoadLibrary``, which in an *unhooked* process happily loads a
fresh copy off PATH. ``RENDERDOC_GetAPI`` then succeeds and every capture call
returns cleanly while capturing nothing -- a silent no-op that looks exactly
like a working trace until you go looking for the files. ``GetModuleHandleW``
returns NULL unless the DLL is genuinely already resident, so a run that was not
launched under RenderDoc fails loudly at connect time.

The struct layout below is transcribed from ``RENDERDOC_API_1_6_0`` in
``extern/renderdoc/include/renderdoc_app.h`` of the Blender fork. It is
positional -- a wrong field order calls the wrong function pointer -- so it is
checked at connect time against ``GetAPIVersion``, which must agree with the
version we asked for. Each ``union`` in the header is a single pointer slot.
"""

import ctypes
import os

# ``RENDERDOC_CC`` is ``__cdecl`` on Windows and empty elsewhere; CFUNCTYPE is
# cdecl on every platform, so it is correct for all three.
_FUNC = ctypes.CFUNCTYPE

c_int = ctypes.c_int
c_uint32 = ctypes.c_uint32
c_uint64 = ctypes.c_uint64
c_float = ctypes.c_float
c_char_p = ctypes.c_char_p
c_void_p = ctypes.c_void_p
POINTER = ctypes.POINTER

# ``RENDERDOC_DevicePointer`` / ``RENDERDOC_WindowHandle``. Passing NULL for both
# means "whatever device and window are currently active", which is what we want:
# GHOST owns Blender's and we have no handle to it.
DEVICE = c_void_p
WINDOW = c_void_p

API_VERSION_1_6_0 = 10600

# RENDERDOC_CaptureOption
OPT_ALLOW_VSYNC = 0
OPT_ALLOW_FULLSCREEN = 1
OPT_API_VALIDATION = 2
OPT_CAPTURE_CALLSTACKS = 3
OPT_HOOK_INTO_CHILDREN = 7
OPT_REF_ALL_RESOURCES = 8
OPT_CAPTURE_ALL_CMD_LISTS = 10

# RENDERDOC_OverlayBits
OVERLAY_NONE = 0


class RenderDocAPI_1_6_0(ctypes.Structure):
    _fields_ = [
        ("GetAPIVersion", _FUNC(None, POINTER(c_int), POINTER(c_int), POINTER(c_int))),
        ("SetCaptureOptionU32", _FUNC(c_int, c_int, c_uint32)),
        ("SetCaptureOptionF32", _FUNC(c_int, c_int, c_float)),
        ("GetCaptureOptionU32", _FUNC(c_uint32, c_int)),
        ("GetCaptureOptionF32", _FUNC(c_float, c_int)),
        ("SetFocusToggleKeys", _FUNC(None, POINTER(c_int), c_int)),
        ("SetCaptureKeys", _FUNC(None, POINTER(c_int), c_int)),
        ("GetOverlayBits", _FUNC(c_uint32)),
        ("MaskOverlayBits", _FUNC(None, c_uint32, c_uint32)),
        # union { Shutdown; RemoveHooks; }
        ("RemoveHooks", _FUNC(None)),
        ("UnloadCrashHandler", _FUNC(None)),
        # union { SetLogFilePathTemplate; SetCaptureFilePathTemplate; }
        ("SetCaptureFilePathTemplate", _FUNC(None, c_char_p)),
        # union { GetLogFilePathTemplate; GetCaptureFilePathTemplate; }
        ("GetCaptureFilePathTemplate", _FUNC(c_char_p)),
        ("GetNumCaptures", _FUNC(c_uint32)),
        # ``filename`` is an out buffer, so it must be POINTER(c_char): ctypes
        # refuses to pass a mutable buffer through a c_char_p argument.
        ("GetCapture", _FUNC(c_uint32, c_uint32, POINTER(ctypes.c_char),
                             POINTER(c_uint32), POINTER(c_uint64))),
        ("TriggerCapture", _FUNC(None)),
        # union { IsRemoteAccessConnected; IsTargetControlConnected; }
        ("IsTargetControlConnected", _FUNC(c_uint32)),
        ("LaunchReplayUI", _FUNC(c_uint32, c_uint32, c_char_p)),
        ("SetActiveWindow", _FUNC(None, DEVICE, WINDOW)),
        ("StartFrameCapture", _FUNC(None, DEVICE, WINDOW)),
        ("IsFrameCapturing", _FUNC(c_uint32)),
        ("EndFrameCapture", _FUNC(c_uint32, DEVICE, WINDOW)),
        ("TriggerMultiFrameCapture", _FUNC(None, c_uint32)),
        ("SetCaptureFileComments", _FUNC(None, c_char_p, c_char_p)),
        ("DiscardFrameCapture", _FUNC(c_uint32, DEVICE, WINDOW)),
        ("ShowReplayUI", _FUNC(c_uint32)),
        ("SetCaptureTitle", _FUNC(None, c_char_p)),
    ]


class NotHooked(RuntimeError):
    """Raised when the process was not launched under RenderDoc."""


def _module_handle(name):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.restype = c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    return kernel32.GetModuleHandleW(name), kernel32


class Capture:
    """Thin wrapper over the RenderDoc in-application API.

    ``connect()`` is the only constructor -- it raises :class:`NotHooked` rather
    than returning a stub, because a capture harness that silently records
    nothing is worse than one that fails.
    """

    def __init__(self, api):
        self.api = api
        self.out_dir = None

    @classmethod
    def connect(cls):
        if os.name != "nt":
            # POSIX would use dlopen(RTLD_NOLOAD) here; nothing needs it yet.
            raise NotHooked("gpu_trace only implements the Windows hook check")

        handle, kernel32 = _module_handle("renderdoc.dll")
        if not handle:
            raise NotHooked(
                "renderdoc.dll is not loaded in this process -- launch Blender via "
                "'renderdoccmd capture -- blender.exe ...' or RenderDoc's Launch Application")

        kernel32.GetProcAddress.restype = c_void_p
        kernel32.GetProcAddress.argtypes = [c_void_p, c_char_p]
        addr = kernel32.GetProcAddress(handle, b"RENDERDOC_GetAPI")
        if not addr:
            raise NotHooked("renderdoc.dll is loaded but exports no RENDERDOC_GetAPI")

        get_api = _FUNC(c_int, c_int, POINTER(POINTER(RenderDocAPI_1_6_0)))(addr)
        api_ptr = POINTER(RenderDocAPI_1_6_0)()
        if not get_api(API_VERSION_1_6_0, ctypes.byref(api_ptr)) or not api_ptr:
            raise NotHooked("RENDERDOC_GetAPI refused version 1.6.0")

        api = api_ptr.contents
        # Guards the positional struct layout: if the resident RenderDoc were
        # older than 1.6 it would have refused above, and if these three slots
        # read back as anything but a sane version the field order is wrong.
        major, minor, patch = c_int(), c_int(), c_int()
        api.GetAPIVersion(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
        if (major.value, minor.value) < (1, 6):
            raise NotHooked("RenderDoc API reports {}.{}.{}, need >= 1.6".format(
                major.value, minor.value, patch.value))

        self = cls(api)
        self.version = (major.value, minor.value, patch.value)
        return self

    # -- configuration ------------------------------------------------------

    def configure(self, out_dir, prefix):
        """Point captures at ``out_dir/prefix_frameN.rdc`` and silence the overlay.

        The overlay is drawn into the swapchain every frame; leaving it on would
        add text rendering to exactly the frames being measured, and it differs
        between the two arms only by accident.
        """
        os.makedirs(out_dir, exist_ok=True)
        self.out_dir = out_dir
        template = os.path.join(out_dir, prefix)
        self.api.SetCaptureFilePathTemplate(template.encode("utf-8"))
        self.api.MaskOverlayBits(OVERLAY_NONE, OVERLAY_NONE)
        # Blender is also passed --gpu-vsync off; this covers the case where a
        # driver-level override would otherwise re-enable it under the hook.
        self.api.SetCaptureOptionU32(OPT_ALLOW_VSYNC, 0)
        # API validation would change driver behaviour inside the measured
        # frames, and callstack capture is very slow per action.
        self.api.SetCaptureOptionU32(OPT_API_VALIDATION, 0)
        self.api.SetCaptureOptionU32(OPT_CAPTURE_CALLSTACKS, 0)
        return template

    def set_title(self, title):
        self.api.SetCaptureTitle(title.encode("utf-8"))

    # -- triggering ---------------------------------------------------------

    def trigger_multi(self, num_frames):
        """Capture the next ``num_frames`` presents as that many separate files.

        This, rather than a StartFrameCapture/EndFrameCapture pair spanning the
        whole stroke, is what makes a stroke tractable: RenderDoc's replay
        analysis is per-frame, and one capture holding 20 presents replays as a
        single enormous frame whose per-action costs cannot be attributed back
        to individual dabs.
        """
        self.api.TriggerMultiFrameCapture(int(num_frames))

    def is_capturing(self):
        return bool(self.api.IsFrameCapturing())

    def num_captures(self):
        return int(self.api.GetNumCaptures())

    def captures(self):
        """Absolute paths of every capture written so far, oldest first."""
        paths = []
        for index in range(self.num_captures()):
            length = c_uint32()
            if not self.api.GetCapture(index, None, ctypes.byref(length), None):
                continue
            buffer = ctypes.create_string_buffer(length.value + 1)
            timestamp = c_uint64()
            if not self.api.GetCapture(index, buffer, ctypes.byref(length), ctypes.byref(timestamp)):
                continue
            paths.append({
                "path": buffer.value.decode("utf-8", "replace"),
                "timestamp": int(timestamp.value),
            })
        return paths
