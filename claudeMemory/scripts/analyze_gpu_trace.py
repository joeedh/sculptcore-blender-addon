# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Replay-side analysis of the .rdc captures a bench run produced.

Runs inside RenderDoc, not Blender::

    qrenderdoc.exe --python analyze_gpu_trace.py

Three properties of that host shape the file, and all three cost time to
rediscover:

* ``qrenderdoc`` is a **GUI-subsystem** binary, so nothing written to stdout
  reaches a parent process. Every result goes to a file.
* The embedded interpreter execs this script **without setting ``__file__``**,
  so a path derived from it raises ``NameError`` before the first line of real
  work -- and because the failure happens before any output exists, it presents
  as "the script never ran". The job description therefore arrives through the
  ``SC_GPU_TRACE_JOB`` environment variable.
* ``--python`` runs *before* the main UI opens, and the UI opens regardless when
  the script returns. ``os._exit(0)`` at the end is what keeps this headless.

The interpreter is Python 3.6, so no walrus, no f-string ``=``, no dataclasses.

Job file (JSON)::

    {"captures": [{"label": "native", "path": "C:/.../native_frame123.rdc"}, ...],
     "out": "C:/.../gpu_stats.json"}
"""

import io
import json
import os
import sys
import traceback

JOB_ENV = "SC_GPU_TRACE_JOB"


def load_job():
    path = os.environ.get(JOB_ENV)
    if not path:
        raise RuntimeError("{} is not set".format(JOB_ENV))
    # utf-8-sig, not the platform default: the job may be written by any tool,
    # and a BOM (or a non-cp1252 path) would otherwise fail before any work.
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Counter plumbing
# ---------------------------------------------------------------------------


def succeeded(result, rd):
    """True if a RenderDoc call succeeded, across both result conventions.

    Older builds return a bare ``ResultCode``; current ones return a
    ``ResultDetails`` carrying a code plus a message. Comparing the latter
    against ``ResultCode.Succeeded`` is not an error -- it just yields False
    forever -- so the richer type is checked first.
    """
    ok = getattr(result, "OK", None)
    if callable(ok):
        return bool(ok())
    return result == rd.ResultCode.Succeeded


def counter_value(result, description, rd):
    """Pull the right union member for a counter result.

    ``CounterResult.value`` is a union; which member holds the number is given
    by the counter's own description, not by the result. Reading the wrong one
    returns plausible garbage rather than failing, so this is worth doing
    properly.
    """
    comp_type = description.resultType
    width = description.resultByteWidth
    if comp_type == rd.CompType.Float:
        return float(result.value.d if width == 8 else result.value.f)
    if comp_type == rd.CompType.UInt:
        return float(result.value.u64 if width == 8 else result.value.u32)
    if comp_type == rd.CompType.SInt:
        return float(result.value.s64 if width == 8 else result.value.s32)
    return float(result.value.d)


def duration_to_ms(value, description, rd):
    """Counter units are per-counter; EventGPUDuration is seconds on most APIs."""
    unit = getattr(description, "unit", None)
    if unit == rd.CounterUnit.Seconds:
        return value * 1000.0
    if unit == getattr(rd.CounterUnit, "Milliseconds", None):
        return value
    # Unknown unit: report raw so it is obviously not milliseconds.
    return value


def flatten_actions(actions):
    for action in actions:
        yield action
        for child in flatten_actions(action.children):
            yield child


def classify(action, rd):
    """Bucket an action, most specific flag first."""
    flags = action.flags
    for name in ("Dispatch", "MeshDispatch", "Drawcall", "Copy", "Resolve", "Clear", "Present"):
        flag = getattr(rd.ActionFlags, name, None)
        if flag is not None and (flags & flag):
            return name
    return "Other"


def analyze_capture(path, rd):
    stats = {"path": path}

    capture = rd.OpenCaptureFile()
    result = capture.OpenFile(path, "", None)
    if not succeeded(result, rd):
        capture.Shutdown()
        stats["error"] = "OpenFile failed: {}".format(str(result))
        return stats

    if not capture.LocalReplaySupport():
        capture.Shutdown()
        stats["error"] = "no local replay support for this capture"
        return stats

    result, controller = capture.OpenCapture(rd.ReplayOptions(), None)
    if not succeeded(result, rd) or controller is None:
        capture.Shutdown()
        stats["error"] = "OpenCapture failed: {}".format(str(result))
        return stats

    try:
        actions = list(flatten_actions(controller.GetRootActions()))
        stats["api"] = str(controller.GetAPIProperties().pipelineType)

        buckets = {}
        vertices = 0
        instances = 0
        for action in actions:
            kind = classify(action, rd)
            buckets[kind] = buckets.get(kind, 0) + 1
            if kind == "Drawcall":
                vertices += int(getattr(action, "numIndices", 0) or 0)
                instances += int(getattr(action, "numInstances", 0) or 0)
        stats["actions"] = buckets
        stats["action_total"] = len(actions)
        stats["draw_vertices"] = vertices
        stats["draw_instances"] = instances

        # -- GPU time per event, folded back onto the action buckets ---------
        available = controller.EnumerateCounters()
        if rd.GPUCounter.EventGPUDuration not in available:
            stats["gpu_error"] = "EventGPUDuration not exposed by this driver"
            return stats

        description = controller.DescribeCounter(rd.GPUCounter.EventGPUDuration)
        results = controller.FetchCounters([rd.GPUCounter.EventGPUDuration])
        by_event = {}
        for entry in results:
            by_event[entry.eventId] = duration_to_ms(
                counter_value(entry, description, rd), description, rd)

        gpu_by_kind = {}
        per_action = []
        for action in actions:
            ms = by_event.get(action.eventId)
            if ms is None:
                continue
            kind = classify(action, rd)
            gpu_by_kind[kind] = gpu_by_kind.get(kind, 0.0) + ms
            per_action.append({"name": action.GetName(controller.GetStructuredFile()),
                               "kind": kind, "ms": ms, "event": int(action.eventId)})

        stats["gpu_ms_by_kind"] = gpu_by_kind
        # Sum over *leaf* events only would double-count nothing, but markers and
        # parents also carry durations; report both so a reader can tell.
        stats["gpu_ms_total"] = sum(gpu_by_kind.values())
        per_action.sort(key=lambda row: -row["ms"])
        stats["top_actions"] = per_action[:15]
    finally:
        controller.Shutdown()
        capture.Shutdown()

    return stats


def main():
    job = load_job()
    out_path = job["out"]
    report = {"captures": []}

    try:
        import renderdoc as rd
    except Exception as ex:
        report["error"] = "import renderdoc failed: {}: {}".format(type(ex).__name__, ex)
        with open(out_path, "w") as handle:
            json.dump(report, handle, indent=2)
        return

    report["renderdoc_version"] = rd.GetVersionString()
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    try:
        for entry in job["captures"]:
            try:
                stats = analyze_capture(entry["path"], rd)
            except Exception:
                stats = {"path": entry["path"], "error": traceback.format_exc()}
            stats["label"] = entry.get("label", "")
            report["captures"].append(stats)
    finally:
        rd.ShutdownReplay()

    with open(out_path, "w") as handle:
        json.dump(report, handle, indent=2)


try:
    main()
except Exception:
    # Nothing here can reach a console, so a crash must still leave a trace on
    # disk or the driver sees only an empty result.
    try:
        fallback = os.environ.get(JOB_ENV, "") + ".error.txt"
        with open(fallback, "w") as handle:
            handle.write(traceback.format_exc())
    except Exception:
        pass

sys.stdout.flush()
os._exit(0)
