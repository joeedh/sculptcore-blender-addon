---
name: ship-sculptblender
description: Run the SculptBlender packaging pipeline end to end — reuse the Blender fork's existing CI build when a valid one already exists for its head commit (dispatching build.yml only when it does not), then run build-packages.yml pinned to that run, publish any freshly-built native deps, and verify the published release. Use when the user asks to "ship a build", "run the packaging pipeline", "cut a new SculptBlender release", "publish new packages", or similar.
---

# Ship a SculptBlender package release

Two GitHub workflows in two repos, plus a manual deps hand-off, produce one
release on `joeedh/sculptblender-builds`. This skill drives all of it.

**Cost awareness.** The fork build is ~2.5 h of CI; packaging is ~10 min with a
warm deps cache and ~2 h without. Tell the user at the start which of those you
are about to spend, based on what Phase 1 finds. Do not dispatch the fork build
"just in case" — Phase 1 exists precisely to avoid it.

Constants:

| thing | value |
| --- | --- |
| fork repo / branch | `joeedh/blender` / `custom-object-modes` |
| fork workflow | `build.yml` (no inputs) |
| addon repo / branch | `joeedh/sculptcore-blender-addon` / `master` |
| packaging workflow | `build-packages.yml` |
| builds repo | `joeedh/sculptblender-builds` |
| deps repo | `joeedh/sculptcore-deps` |

## Watching a run (both builds are hours long — get this right)

Use a **persistent `Monitor`**, not a backgrounded Bash loop. A `run_in_background`
loop is killed at turn boundaries — observed dying after 30 min, and on the next
two attempts after a *single* iteration — so the watch silently stops while the
run keeps going and you learn nothing until you happen to poll by hand. `Monitor`
with `persistent: true` survives the full ~2.5 h. Never foreground-`sleep` either;
the harness blocks `sleep N; <check>` chains outright.

```sh
prev=""
while :; do
  cur=$(gh run view <id> --repo <repo> --json status,conclusion,jobs \
        -q '(.status+"/"+(if (.conclusion//"")=="" then "running" else .conclusion end))+" | "+([.jobs[]|.name+"="+(if (.conclusion//"")=="" then .status else .conclusion end)]|join(", "))' 2>&1 || echo "poll-error")
  if [ "$cur" != "$prev" ]; then echo "$(date -u +%H:%M) $cur"; prev="$cur"; fi
  case "$cur" in completed/*) echo "TERMINAL: $cur"; break;; esac
  sleep 300
done
```

Three things that shape gets right:

- **`gh` returns `conclusion` as `""`, not `null`, for anything unfinished**, so
  jq's `//` fallback never fires — `(.conclusion // .status)` renders every job
  blank. Test the empty string explicitly, as above. (Terminal detection still
  works with the naive version, which is what makes the bug easy to miss.)
- **Emit only on change.** One notification per state transition, not one per
  poll — a 2.5 h run at 300 s polls is ~30 messages of pure noise otherwise.
- **Cover every terminal state**, not just success: matching `completed/*` and
  printing the whole job list means a `failure`/`cancelled` wakes you the same
  way a success does. A filter that watches only for the happy path is silent
  through a failure, and silence is indistinguishable from "still running".

Stop the monitor with `TaskStop` if you need to restart it with a fixed query.

This applies to **watching a run over time**. A one-shot command that exits on
its own — the LFS push in Phase 4, waiting for a cancel to settle — is still fine
as Bash `run_in_background`; it ends in seconds-to-minutes and gives you a single
completion notification. The turn-boundary kill only bites open-ended loops.

## Phase 0 — Preflight

1. `gh auth status` must be authenticated.
2. The packaging workflow runs the code **at the ref on the remote**, not your
   working tree. From the addon repo, confirm there is nothing unpushed that
   the release is supposed to contain:
   `git -C <addon> log --oneline origin/master..master` and
   `git -C <addon> status --short`.
   If packaging-relevant work is unpushed, say so and stop — pushing is the
   user's call, not this skill's.

## Phase 1 — Is there already a valid fork build? (the skill's whole point)

"Valid" means: a **successful** `build.yml` run whose `headSha` is the branch's
current head, **and** whose three install artifacts are still downloadable
(GitHub expires artifacts; a run that is green but expired is useless here).

```sh
sha=$(git ls-remote https://github.com/joeedh/blender.git refs/heads/custom-object-modes | cut -f1)
run=$(gh run list --repo joeedh/blender --workflow build.yml \
        --branch custom-object-modes --limit 20 \
        --json databaseId,headSha,conclusion \
        -q "[.[]|select(.headSha==\"$sha\" and .conclusion==\"success\")][0].databaseId")
gh api repos/joeedh/blender/actions/runs/$run/artifacts \
  -q '[.artifacts[]|select(.expired==false)|.name]|sort|join(", ")'
```

Accept the run only if that last command lists all three of
`blender-install-Linux`, `blender-install-Windows`, `blender-install-macOS`.
Otherwise treat it as no valid build and go to Phase 2.

Report which branch it is: *"fork head `<sha>` already has a valid build (run
`<id>`), skipping the 2.5 h build"* or *"no valid build for fork head `<sha>`,
dispatching build.yml"*.

## Phase 2 — Build the fork (only if Phase 1 found nothing)

```sh
gh workflow run build.yml --repo joeedh/blender --ref custom-object-modes
```

`workflow run` prints nothing useful, so resolve the run id afterwards by
listing runs for that branch and taking the newest whose `headSha` matches
`$sha` (the same query as Phase 1, minus the conclusion filter). Confirm it is
`in_progress` at the expected sha before you start polling — a dispatch that
raced a push would otherwise be polled to completion for the wrong commit.

Poll to completion. All three matrix jobs must be `success`; if any failed,
stop and report — do not package a partial build.

A green build is not automatically packageable: `master` will have moved during
those ~2.5 h. Phase 3's precondition re-checks it before anything is dispatched.

## Phase 3 — Package

### Precondition: re-read `origin/master` and check the ABI pairing

Do this immediately before dispatching, **not** at Phase 0. The fork build takes
~2.5 h and both refs move during it — a build can be superseded by a commit that
did not exist when it was dispatched, so a sha you validated earlier proves
nothing now.

```sh
git -C <addon> fetch origin master -q && git -C <addon> rev-parse origin/master
```

Packaging pairs the **fork build** with the **addon + engine submodule at
`origin/master`**. Those move independently, and a green fork build does not mean
the pair agrees on the **external-draw ABI**. Nothing in either workflow checks
this. Verify by hand that the fork sha you are about to pin carries the ABI the
engine submodule was bumped to:

```sh
git -C <fork> grep -l bl_draw_provider_abi_version <fork-sha>   # empty = too old
git -C <addon> rev-parse origin/master:engine                   # then read its log for extdraw bumps
```

If the addon side bumped the extdraw ABI and the fork sha lacks the property,
**stop — do not package.** Blender rejects a mismatched provider *silently*: the
result is a base-cage viewport with no engine geometry, and the addon takes its
"fork predates the property, register anyway" path rather than erroring. The
auto-triggered smoke test fails the release too, so the run can only waste its
CI. Rebuild the fork at a tip that has the property.

Fork extdraw commits and engine extdraw commits land as **matched pairs** authored
minutes apart; an unpaired one is a rebuild trigger. Not every skew is fatal —
an engine change that merely stops *advertising* a slot (an older fork fills
neutral zeros) costs perf, not correctness. A **version** bump is the hard break.

### Dispatch

```sh
gh workflow run build-packages.yml --repo joeedh/sculptcore-blender-addon \
  --ref master -f blender_run=<fork run id>
```

**Always pass `blender_run`.** Blank means "latest successful run on
`blender_branch`", which can silently package a Blender that predates the fork
change being shipped. Other inputs, all optional: `blender_branch`, `config`
(`RelWithDebInfo`|`Release`), `tag` (default `build-<UTC date>-<short sha>`),
`prerelease` (default **false** — GitHub's `/releases/latest` skips pre-releases
entirely, so marking one keeps it off the stable download links). Pass them only
if the user asked for them.

Resolve the run id from the command's output URL, verify its `headSha` is the
addon repo's `origin/master`, then poll. Jobs: `Prepare release`, the three
matrix jobs, `Publish`.

## Phase 4 — Publish freshly-built native deps (do not skip)

A packaging job that hit a cold deps cache compiled OpenBLAS + SuiteSparse from
source and exported the result. Publishing it is what keeps the *next* run at
minutes instead of hours, and nothing is pushed from the runner.

```sh
gh api repos/joeedh/sculptcore-blender-addon/actions/runs/<pkg run>/artifacts \
  -q '.artifacts[]|.name'
```

For every artifact named `deps-<label>-<config>`:

```sh
gh run download <pkg run> --repo joeedh/sculptcore-blender-addon \
  --name "deps-Linux x64-RelWithDebInfo" --dir <scratch>/deps-linux
node engine/tools/publish-deps-from-package.mjs <scratch>/deps-linux --dry-run
node engine/tools/publish-deps-from-package.mjs <scratch>/deps-linux --commit --push
```

Run from inside `engine/`. Always `--dry-run` first and read it: it must say
the combo *is new*. If it reports the combo as already published, do not push —
investigate instead, because the runner should not have rebuilt it. The static
libs go through git-LFS (a few minutes for the ~160 MB Linux combo), so run the
push backgrounded.

If a run produced **no** `deps-*` artifacts, every combo was a cache hit —
that is the healthy steady state, not a problem.

## Phase 5 — Verify the release

Do not trust a green run alone; check the artifacts the user will actually
download. The release tag is `build-<date>-<short addon sha>`.

1. **Add-on came up enabled** — each matrix job's log must contain
   `verify_addon: 'sculptcore_addon' enabled by default (no userpref)`.
   ```sh
   gh run view <pkg run> --repo joeedh/sculptcore-blender-addon --log \
     --job $(gh run view <pkg run> --repo joeedh/sculptcore-blender-addon \
       --json jobs -q '.jobs[]|select(.name=="Linux x64")|.databaseId') | grep verify_addon
   ```
2. **One top-level folder per archive**, without downloading ~1.5 GB. For a
   tarball, a ranged read of the first ~1.5 MB lists its leading entries:
   ```sh
   curl -sL -r 0-1500000 "<asset url>" -o head.bin && tar -tzf head.bin 2>/dev/null | head -5
   ```
   For the zip, read the first local file header's name (offset 30, length at
   offset 26) from the first few hundred bytes. Every entry must sit under
   `sculptblender-<tag>-<platform>/`.
3. **Index ordering** — the new tag must be first in the builds repo's
   `RELEASES.md`, and its `releases/<tag>.json` must carry a `created_at`.

Report: run URLs, the release tag and its assets with sizes, per-job durations
(they say whether the deps cache hit), and the result of each check above.

## Troubleshooting

| symptom | cause |
| --- | --- |
| Packaging fails at "Assemble Blender + addon" with *"is this a fork build with the .always_enable support"* | The pinned fork build predates that `addon_utils.py` change. Build the fork at a newer head. |
| Packaging can't download the fork artifacts | `BUILDS_TOKEN` secret — needs `actions:read` on `joeedh/blender` and `contents:write` on `joeedh/sculptblender-builds`. The default `GITHUB_TOKEN` is repo-scoped and cannot. |
| Addon reports `kernel 'NUDGE' missing from engine enum` | Engine libs built without `--kernels-extra ../brushes`. |
| Phase 1 finds a green run whose artifacts are expired | Treat as no build; dispatch a fresh one. |
| Packaged viewport shows the base cage / no engine geometry; smoke test fails on null provider or missing `bl_draw_provider_abi_version` | External-draw ABI skew: the pinned fork build predates the ABI the engine submodule was bumped to. Blender rejects the provider silently. Rebuild the fork at a tip carrying the property — see the Phase 3 precondition. |
| The fork build you just waited 2.5 h for is already superseded | Normal: `master` moves during the build. Re-read `origin/master` at Phase 3 and re-check the ABI pairing before dispatching. Nothing is salvageable from the stale build if the ABI moved. |

Background: `CLAUDE.md` § *Packaging CI* in this repo.
