# Opt-in Blender Python debug server

Status: implemented and verified 2026-09-15. User authorized this development tool on 2026-09-15.

## Scope and contract

* Add `sculptcore_addon/debug_server.py`, disabled until explicitly started.
  Bind only IPv4 loopback, choose an ephemeral port by default, generate a
  per-start token, and return connection information to the caller.
* Standard-library TCP transport, one bounded JSON-line request/reply per
  connection. Requests support `ping`, `eval`, and `exec`; replies report
  success, expression repr, captured stdout/stderr, and formatted exceptions.
  Authentication happens before anything is queued. No automatic retries.
* Network threads perform socket I/O only. A Blender timer drains a bounded
  request queue on the main thread, executing Python in a persistent namespace
  initially containing `bpy`. Provide an explicit main-thread pump for controlled
  background harnesses whose event loop does not run.
* Limit connections, frame size, queued requests, captured output and jobs per
  timer tick. Queue timeout cancels work before it starts; timeout after execution
  starts reports uncertain/in-progress completion and must not trigger a retry.
  Arbitrary Python itself cannot be safely preempted; blocking code blocks Blender.
* Synchronous bind errors must surface to the caller. Stop releases the socket,
  pending requests, timer and handlers without waiting for main-thread work.
  Stop on file load and add-on unregister; persistent Python references must not
  survive a replaced Blender database. Starting twice is idempotent; restart
  creates a fresh token and namespace. Re-import/reload must not orphan a server.
* Add `tools/blender_debug.py` as startup helper and one-shot CLI client. An
  explicitly supplied connection file holds host/port/token for test-owned
  sessions; do not auto-enable through saved preferences or ship credentials.
  Document context overrides, main-thread constraints and headless pumping.

## Implementation steps

1. Implement server, lifecycle integration in add-on unregister, startup helper
   and client. The startup helper may load the workspace server module into an
   already installed add-on for development without restaging the engine DLL.
2. Add standard-library protocol/lifecycle tests: authentication, malformed and
   oversized input, exception capture, namespace persistence, queued cancellation,
   bounded output, port collision, stop/restart, main-thread execution.
3. Run real Blender background tests with explicit pumping, plus headed tests
   using actual timers and an independent client thread/process. Inspect state,
   modify a scratch custom property, assert main-thread execution, exercise
   stop/file-load behavior, and terminate only test-owned Blender instances.
4. Document exact launch/client examples and add the server to the generic
   brush plan's test infrastructure. Record test commands and limitations.

## Review record

Independent lifecycle/buildability and protocol/testing reviews identified these
requirements, folded into implementation before coding:

* Use atomic queued/running/cancelled/done transitions under a job lock. Test
  cancellation and uncertain running completion separately.
* Admit workers before thread creation; use an absolute request-read deadline,
  track accepted sockets, and close them on stop. Bound the encoded response
  as well as captured streams, result repr and exception text.
* Catch BaseException from submitted code and repr, with a defensive formatting
  fallback. Arbitrary execution and repr remain non-preemptible.
* Enforce main-thread start/stop/pump and reject recursive pumping. Stop at
  load_pre, including failed loads. Reload stops the previous singleton.
* Workspace injection must stop the old canonical module, replace sys.modules
  and the package attribute, and wrap an older installed addon's unregister
  once to supply the missing cleanup hook. Publish credentials atomically
  only after startup; connection files are explicitly caller-managed and may
  remain stale after stop (tokens rotate). Never auto-retry commands.
* Background tests pump explicitly; headed tests use actual timers, a host
  deadline, and cleanup limited to the newly launched test process.

Historical reference: fork commit `47df4abf422697b1f8dfb38f8cfc917f52c3da55`
contained `claudeMemory/scripts/remote_repl.py` (TCP port 4444, NUL framing,
main-thread timer dispatch); it is absent from the current fork checkout.

## Completion

- [x] Server, addon lifecycle hook and standalone startup/client tooling.
- [x] Twelve stdlib protocol/lifecycle tests passed with real sockets.
- [x] Real Blender 5.3.0 Alpha background integration passed using explicit pumping.
- [x] Real headed Blender integration passed using actual app timers and an
  independent client, including a separate-process CLI request.
- [x] Successful and failed file-load cleanup, token rotation and addon disable
  verified in both modes. Both test-owned instances exited successfully.
- [x] Documented startup command independently tested end to end with CLI ping,
  exec and eval (`BLENDER_DEBUG_STARTUP_PASS`).
- [x] [Usage/reference guide](../codebase/blender-debug-server.md),
  [debugging lessons](../debugging.md) and generic brush test infrastructure updated.

The first background integration harness used `read_factory_settings` then
explicitly unregistered the addon a second time, causing missing RNA metadata.
The corrected harness tests file loading with a temporary save/reopen, and
uses `addon_utils.disable` for the teardown gate. Invalid `.blend` error output
is expected in both successful integration runs; no unexpected traceback remains.
