# Blender native test launcher correction

2026-09-16. Bounded fix for missing-DLL popups from standalone Blender tests.
The diagnostic probe reproduced STATUS_DLL_NOT_FOUND (0xc0000135) for both
owned-curve GTest binaries without Blender's runtime search paths. The eight
engine binaries returned zero directly. Existing Blender success logs contain
actual 14/6 GTest pass markers; they were subsequent correctly configured runs.

Add a Python launcher under claudeMemory/scripts for native console GTests only.
Require explicit Blender bin, asset, release and output directories; select
named test executables under bin/tests. Prepend bin/blender.shared and bin to
the child PATH without changing the user's environment or copying DLLs.
Suppress inherited Windows loader/error dialogs in this launcher process and
restore its prior error mode. Launch with an argument array, bounded timeout and
no console window. Capture full child exit status (including Windows NTSTATUS),
stdout/stderr, command and binary hash in logs/JSON; return failure for any
nonzero status, launch error, timeout or absent GTest pass marker. Do not
translate loader failures into a successful empty test run.

Gate: run the real 14 runtime and 6 codec tests through the launcher. Exercise
invalid/missing executable and timeout/status handling without producing UI.
Record the direct eight-engine-test audit and the Blender rerun, update the
debugging guide, and use this launcher for later standalone Blender native tests.
Do not alter Blender/engine production code or global PATH for this correction.

Adversarial review folded before implementation: status/failure and environment
reviewers independently found that inherited GTest filters/shards could falsely
pass a subset. Clear GTEST_* variables, disable color, and require one completed
run with matching positive run/pass counts and the explicitly expected count.
Resolve/validate input directories and executable basenames, use Blender bin as
cwd, and pass the exact CTest asset/release arguments. Preserve existing error
mode flags while adding all three suppression flags, restoring in finally.
Persist a record even when hashing, spawning or waiting fails; timeout must reap
the child and retain partial output. Negative gate also covers actual suppressed
DLL failure, nonzero status, silent zero exit and zero-test summaries.

## Completion gate — 2026-09-16

Complete. `run_blender_native_tests.py` reran the real owned runtime (14) and
IDProperty codec (6) tests: both status 0, exact completed/pass counts, binary
hashes and output in `tests/native-launcher-verified/`. The failure harness
passed nine cases, including an actual suppressed 0xc0000135 loader failure,
partial-output timeout, nonzero exit, silent/zero/subset false passes, missing
executable and CLI path traversal. It also verified restored error mode and
removed inherited GTest filtering. Evidence: `tests/native-launcher-negative/`.
The separate direct engine audit passed all eight binaries; retained in
`tests/native-loader-probe.json`. These are separate exit-code tests, not GTests.

Verified command (PowerShell, from addon root):

```powershell
& 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/python/bin/python.exe' `
  claudeMemory/scripts/run_blender_native_tests.py `
  --blender-bin C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin `
  --assets-dir C:/dev/blender/main/tests/files `
  --release-dir C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3 `
  --output-dir claudeMemory/tests/native-launcher-verified `
  --test blenkernel_curvemapping_owned_test=14 `
  --test blenkernel_curvemapping_idprop_test=6
```
