# Blender Python debug server

Implemented and tested 2026-09-15. This is an opt-in developer console in
`sculptcore_addon/debug_server.py`. It provides access to the running Blender
Python API, including scene data, registered properties and UI context overrides.
Ordinary add-on registration does not open a listener.

## Start and connect

With the current addon installed, run in Blender's Python Console:

```python
from sculptcore_addon import debug_server
connection = debug_server.start()  # 127.0.0.1, ephemeral port, fresh random token
print(connection)
```

For a test-owned development instance, this startup helper loads the debug
module from this checkout into the staged addon without rebuilding or copying
its engine. Run from the addon repository (PowerShell):

```powershell
$blender = 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe'
$connection = Join-Path $env:TEMP 'sculptcore-debug.json'
& $blender --factory-startup --no-window-focus --python tools/blender_debug.py -- --connection-file $connection
```

The headed Blender event loop serves requests with a timer. From another shell:

```powershell
$python = 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/python/bin/python.exe'
$connection = Join-Path $env:TEMP 'sculptcore-debug.json'
& $python tools/blender_debug.py --connection-file $connection --ping
& $python tools/blender_debug.py --connection-file $connection --eval 'bpy.app.version_string'
& $python tools/blender_debug.py --connection-file $connection --exec 'print(bpy.context.scene.name)'
& $python tools/blender_debug.py --connection-file $connection --file 'path/to/probe.py'
```

The connection file is atomically replaced only after successful startup.
Use a different path per instance. It contains a credential granting arbitrary
Python execution in that Blender process; keep it private. It is caller-managed
and can remain after shutdown, but its token becomes invalid. The server only
binds IPv4 loopback and has no setting for remote network exposure.

To stop locally:

```python
debug_server.stop()
```

Calling it remotely closes the calling connection too; a disconnected reply
does not indicate whether execution completed. Loading a file also stops the
server, even when Blender reaches its load callbacks and subsequently fails to
decode the file. Start a new session after loading. Addon unregister and module
reload stop the server. Repeated `start()` calls reuse a running instance;
stop/start creates a fresh namespace and token. The development helper supplies
an unregister cleanup wrapper when used with an older staged addon.

## Background Blender

Blender's background command-line script does not run the interactive timer
loop. Explicitly request a bounded pumping session:

```powershell
& $blender --background --factory-startup --python-exit-code 1 --python tools/blender_debug.py -- --connection-file $connection --background-seconds 120
```

For custom background harnesses, start the server and call `debug_server.pump()`
repeatedly on Blender's main thread. Put the client in another thread or process;
waiting synchronously for a remote response from the main thread deadlocks the
queue. Network threads never call `bpy`. Start, stop and pump enforce the main
thread, and recursive pumping is rejected.

## Commands, results and limits

One UTF-8 JSON line per TCP connection:

```json
{"token": "TOKEN_FROM_START", "op": "eval", "code": "bpy.context.scene.name"}
```

Operations are `ping`, `eval` and `exec`. Execution uses a persistent namespace
initially containing `bpy`; `eval` returns the expression's `repr`, and `exec`
supports multiline statements. Replies contain `ok`, `status`, `result` on
success, `error` on failure, and captured `stdout`/`stderr` for executed jobs.
Exceptions, including `SystemExit` and failed result repr, become error replies.
CLI exit codes: 0 success, 1 server error, 2 argument/transport failure.

Limits: 8 concurrent connections and queued jobs; 256 KiB request; 5-second
absolute request-read deadline; one job per 50 ms timer tick; 30-second wait
for execution; 32 Ki characters each for result, exception and captured streams;
512 KiB encoded response. Captures/results flag truncation. A reply too large
after JSON encoding returns `response_limit`; the command has already run.

* A job still queued after 30 seconds is atomically cancelled and returns
  `status: cancelled`. It will never execute later.
* A job already running returns `status: unknown` when the wait expires. It may
  finish afterward. Transport timeouts and disconnections also leave completion
  uncertain. The client never retries automatically.
* Python commands and custom `repr` functions cannot be preempted. Blocking code
  blocks Blender; limits bound protocol/captured data, not arbitrary Python's
  allocations or runtime. Python stdout/stderr redirection is process-global
  during execution; native C/C++ console output is not captured.
* File load stops further queued work and clears the server namespace, but
  cannot interrupt the command that initiated the load or erase its own local
  references. Avoid using old RNA references after load or undo.

UI operators may require an explicit context; a timer has no user-selected
Python Console area. For example, send this with `--file`:

```python
window = bpy.context.window_manager.windows[0]
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
region = next(region for region in area.regions if region.type == 'WINDOW')
with bpy.context.temp_override(window=window, area=area, region=region):
    print(bpy.context.area.type)
```

## Validation

Tested on the local Blender 5.3.0 Alpha build above:

* `claudeMemory/scripts/test_blender_debug_server.py`: 12 stdlib tests, real
  sockets with a fake timer registry. Covers authentication, malformed/oversized
  frames, output bounds, queue cancellation, uncertain running completion,
  connection cap/read deadline, namespace, exceptions, lifecycle, reload and
  main-thread/reentrancy guards.
* `claudeMemory/scripts/test_blender_debug_integration.py`: real Blender in
  background and headed modes. Checks main-thread execution, scratch property
  writes, persistent namespace, live UI state/context override, separate-process
  CLI, failed/successful file loads, token rotation and addon unregister.
  The headed run uses actual app timers. Require the matching
  `BLENDER_DEBUG_INTEGRATION_PASS background` or `headed` marker and no unexpected
  traceback; the intentionally invalid `.blend` produces an expected error.
* `claudeMemory/scripts/test_blender_debug_startup.py BLENDER_EXE`: starts an
  owned background process through the documented command, then uses the CLI
  for ping, exec and eval. Requires `BLENDER_DEBUG_STARTUP_PASS`.

Run the stdlib tests and startup harness with ordinary Python. Run the
integration script with `blender --background --factory-startup
--python-exit-code 1 --python SCRIPT`, then repeat without `--background`.
Give headed tests a host deadline and terminate only the process the test
launched if it times out. Background invocation checks cannot substitute for
actual timer dispatch in the headed run.
