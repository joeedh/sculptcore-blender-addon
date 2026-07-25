// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/*
 * fetch-blender-dist.mjs — assemble a runnable Blender install per platform from
 * prebuilt CI artifacts, with the SculptCore sculpt mode bundled and enabled by
 * default.  The download-from-CI sibling of build-blender-dist.mjs: instead of
 * building Blender and the engine DLL locally, it fetches (via `gh`):
 *
 *   - the Blender fork install tree  (joeedh/blender `build.yml`:
 *     `blender-install-<OS>`), and
 *   - the engine native libraries    (joeedh/sculptcore `native-nightly.yml`:
 *     `sculptcore-libs-<OS>-<config>`),
 *
 * then reuses the same bundle steps: copy the addon, vendor the engine runtime
 * (the *local* ctypes package from the pinned submodule + the *fetched* libs),
 * and bake an enabled-by-default userpref.
 *
 * Version coordination (ABI): the ctypes `sculptcore` package is taken from the
 * `engine/` submodule at its checked-out commit, so the engine libs MUST come
 * from that same commit or engine.py's init() will refuse the mismatch.  The
 * engine artifact therefore defaults to the submodule HEAD and FAILS (rather
 * than silently drifting) if no CI run built it — override deliberately with
 * --engine-run / --engine-commit / --engine-latest.  The fork build has no such
 * constraint, so it defaults to the latest successful run.
 *
 * The enable step needs a runnable Blender of the *host* OS, so it bakes the
 * userpref once on the host platform and copies it into every other platform's
 * bundle (userpref.blend is app config and ports across platforms).  If the
 * host OS is not among the requested platforms, enabling is skipped with a
 * warning.
 *
 * Requires the GitHub CLI (`gh`) on PATH and authenticated (`gh auth status`).
 * No npm dependencies — plain Node.
 *
 * Usage:
 *   node tools/fetch-blender-dist.mjs [options]
 *
 *   --platform OS       Target platform, repeatable: windows | linux | macos
 *                       (default: the host OS).
 *   --all               Fetch all three platforms (windows, linux, macos).
 *   --config CFG        Engine libs build config (default: RelWithDebInfo).
 *   --out DIR           Output root; each platform lands in <DIR>/<os>
 *                       (default: <repo>/dist/fetched).
 *   --blender-run ID    Pin the fork build to this Actions run id.
 *   --blender-commit SHA  Pin the fork build to the run for this commit.
 *   --blender-branch B  Branch to pick the latest fork build from
 *                       (default: custom-object-modes).
 *   --engine-run ID     Pin the engine libs to this Actions run id.
 *   --engine-commit SHA Pin the engine libs to the run for this commit
 *                       (default: the engine/ submodule HEAD).
 *   --engine-latest     Use the latest successful engine run instead of the
 *                       submodule commit (accepts the ABI-mismatch risk).
 *   --blender-src DIR   Blender fork checkout, for repo discovery
 *                       (default: ../main, or $BLENDER_SRC).
 *   --no-enable         Skip baking the enabled-by-default userpref.
 *   --keep-tmp          Do not delete the per-run download scratch dir.
 *   -h, --help
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const TOOLS = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(TOOLS, '..')
const ENGINE = path.join(REPO, 'engine')
const ADDON_SRC = path.join(REPO, 'sculptcore_addon')
const ENABLE_PY = path.join(TOOLS, 'enable_addon.py')
const ADDON_MODULE = 'sculptcore_addon'
const PKG_ROOT = path.join(ENGINE, 'python', 'sculptcore')

// runner.os values GitHub uses, keyed by our lowercase platform token.
const OS_TOKENS = { windows: 'Windows', linux: 'Linux', macos: 'macOS' }
const NODE_PLATFORM_TO_OS = { win32: 'windows', linux: 'linux', darwin: 'macos' }

// Shared-library file names an engine libs artifact carries, per target OS.
function libNamesFor(osToken) {
  if (osToken === 'windows') return ['sculptcore_capi.dll', 'wgpu_native.dll']
  if (osToken === 'macos') return ['libsculptcore_capi.dylib', 'libwgpu_native.dylib']
  return ['libsculptcore_capi.so', 'libwgpu_native.so']
}

// --- tiny arg parser -------------------------------------------------------

function parseArgs(argv) {
  const opts = {
    platforms: [],
    all: false,
    config: 'RelWithDebInfo',
    out: path.join(REPO, 'dist', 'fetched'),
    blenderRun: null,
    blenderCommit: null,
    blenderBranch: 'custom-object-modes',
    engineRun: null,
    engineCommit: null,
    engineLatest: false,
    blenderSrc: process.env.BLENDER_SRC || path.resolve(REPO, '..', 'main'),
    enable: true,
    keepTmp: false,
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    switch (a) {
      case '--platform': {
        const p = next().toLowerCase()
        if (!(p in OS_TOKENS)) fail(`unknown --platform ${p} (windows|linux|macos)`)
        opts.platforms.push(p)
        break
      }
      case '--all': opts.all = true; break
      case '--config': opts.config = next(); break
      case '--out': opts.out = path.resolve(next()); break
      case '--blender-run': opts.blenderRun = next(); break
      case '--blender-commit': opts.blenderCommit = next(); break
      case '--blender-branch': opts.blenderBranch = next(); break
      case '--engine-run': opts.engineRun = next(); break
      case '--engine-commit': opts.engineCommit = next(); break
      case '--engine-latest': opts.engineLatest = true; break
      case '--blender-src': opts.blenderSrc = path.resolve(next()); break
      case '--no-enable': opts.enable = false; break
      case '--keep-tmp': opts.keepTmp = true; break
      case '-h': case '--help': opts.help = true; break
      default: fail(`unknown option: ${a} (try --help)`)
    }
  }
  if (opts.all) opts.platforms = Object.keys(OS_TOKENS)
  if (!opts.platforms.length) {
    const host = NODE_PLATFORM_TO_OS[process.platform]
    if (!host) fail(`unsupported host platform ${process.platform}; pass --platform`)
    opts.platforms = [host]
  }
  // De-dupe, host first (so its baked userpref is available for the others).
  opts.platforms = [...new Set(opts.platforms)]
  const host = NODE_PLATFORM_TO_OS[process.platform]
  opts.platforms.sort((a, b) => (a === host ? -1 : b === host ? 1 : 0))
  return opts
}

// --- helpers ---------------------------------------------------------------

function log(msg) { console.log(`\x1b[36m[fetch]\x1b[0m ${msg}`) }
function warn(msg) { console.error(`\x1b[33m[fetch] warn:\x1b[0m ${msg}`) }
function fail(msg) { console.error(`\x1b[31m[fetch] error:\x1b[0m ${msg}`); process.exit(1) }

// Run a command, inheriting stdio; returns exit status.
function run(cmd, args, extraEnv) {
  log(`$ ${cmd} ${args.join(' ')}`)
  const res = spawnSync(cmd, args, {
    stdio: 'inherit',
    env: extraEnv ? { ...process.env, ...extraEnv } : process.env,
  })
  if (res.error) fail(`failed to launch ${cmd}: ${res.error.message}`)
  return res.status ?? 0
}

// Run a command capturing stdout (trimmed); fails on non-zero unless allowFail.
function capture(cmd, args, { allowFail = false } = {}) {
  const res = spawnSync(cmd, args, { encoding: 'utf-8' })
  if (res.error) fail(`failed to launch ${cmd}: ${res.error.message}`)
  if (res.status !== 0 && !allowFail) {
    fail(`${cmd} ${args.join(' ')} failed (code ${res.status}):\n${res.stderr || ''}`)
  }
  return { status: res.status ?? 0, stdout: (res.stdout || '').trim(), stderr: res.stderr || '' }
}

function ensureDir(d) { fs.mkdirSync(d, { recursive: true }) }

function copyTree(src, dst, skip = new Set()) {
  ensureDir(dst)
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue
    const s = path.join(src, entry.name)
    const d = path.join(dst, entry.name)
    if (entry.isDirectory()) copyTree(s, d, skip)
    else fs.copyFileSync(s, d)
  }
}

// Parse an owner/repo slug from a github.com remote of a checkout.
function githubSlug(repoDir, label) {
  const { stdout } = capture('git', ['-C', repoDir, 'remote', '-v'], { allowFail: true })
  for (const line of stdout.split('\n')) {
    const m = /github\.com[/:]([^/\s]+)\/([^/\s]+?)(?:\.git)?\s/.exec(line + ' ')
    if (m) return `${m[1]}/${m[2]}`
  }
  fail(`could not find a github.com remote for ${label} in ${repoDir}`)
}

// Resolve an Actions run id for a workflow file, by run id / commit / latest.
function resolveRun({ slug, workflow, runId, commit, branch, label }) {
  if (runId) return runId
  if (commit) {
    const q = `repos/${slug}/actions/workflows/${workflow}/runs?head_sha=${commit}&status=success&per_page=1`
    const { stdout } = capture('gh', ['api', q, '--jq', '.workflow_runs[0].id // ""'])
    if (!stdout) {
      fail(`no successful ${workflow} run for ${label} commit ${commit.slice(0, 12)} in ${slug}.\n` +
        `       Push/build that commit, or override (--${label}-run / --${label}-commit / --${label}-latest).`)
    }
    return stdout
  }
  const q = `repos/${slug}/actions/workflows/${workflow}/runs?status=success&branch=${branch}&per_page=1`
  const { stdout } = capture('gh', ['api', q, '--jq', '.workflow_runs[0].id // ""'])
  if (!stdout) fail(`no successful ${workflow} run on branch ${branch} in ${slug}`)
  return stdout
}

// Download one named artifact from a run into destDir (extracted flat).
function downloadArtifact({ slug, runId, name, destDir }) {
  ensureDir(destDir)
  const status = run('gh', ['run', 'download', String(runId), '-R', slug, '-n', name, '-D', destDir])
  if (status !== 0) {
    fail(`gh run download failed for artifact ${name} (run ${runId}, ${slug}).\n` +
      `       The artifact may have expired (90-day retention) or the run predates it.`)
  }
}

// Find the Blender resource dir (a `<major>.<minor>` folder containing scripts/)
// anywhere within an install tree — works for win/linux bin trees and the macOS
// Blender.app bundle without running the binary. Returns null (soft) or fails.
function findVersionDir(root, { soft = false } = {}) {
  const stack = [root]
  while (stack.length) {
    const dir = stack.pop()
    let entries
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { continue }
    for (const e of entries) {
      if (!e.isDirectory()) continue
      const child = path.join(dir, e.name)
      if (/^\d+\.\d+$/.test(e.name) && fs.existsSync(path.join(child, 'scripts'))) return child
      stack.push(child)
    }
  }
  if (soft) return null
  fail(`could not locate a Blender <version>/scripts dir under ${root}`)
}

// Locate an already-baked userpref.blend from a previously-staged host bundle,
// so non-host platforms can be fetched in a separate invocation and still get
// enabled by default.
function findHostUserpref(outRoot, hostOs) {
  if (!hostOs) return null
  const verDir = findVersionDir(path.join(outRoot, hostOs), { soft: true })
  if (!verDir) return null
  const up = path.join(verDir, 'config', 'userpref.blend')
  return fs.existsSync(up) ? up : null
}

// Copy the ctypes package + fetched libs into <addon>/lib/sculptcore.
function vendorRuntime(addonDir, libsDir, osToken) {
  const dest = path.join(addonDir, 'lib', 'sculptcore')
  fs.rmSync(dest, { recursive: true, force: true })
  copyTree(PKG_ROOT, dest, new Set(['__pycache__', '.mypy_cache']))
  // The engine libs artifact carries the shared libs flat; stage the ones for
  // this OS beside the package (_capi.py resolves the lib next to itself).
  const wanted = new Set(libNamesFor(osToken))
  const found = new Set()
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (wanted.has(e.name)) { fs.copyFileSync(p, path.join(dest, e.name)); found.add(e.name) }
    }
  }
  walk(libsDir)
  const [capi] = libNamesFor(osToken)
  if (!found.has(capi)) fail(`engine libs artifact for ${osToken} is missing ${capi} (looked in ${libsDir})`)
  for (const n of wanted) if (!found.has(n)) warn(`engine lib ${n} not in artifact; not staged`)
}

// Restore the Unix executable bit on a non-Windows bundle's binaries. GitHub
// artifacts are zipped without Unix permissions, so the fetched `blender` binary
// (and the bundled Python interpreter) arrive as 0644 and won't launch. NOTE:
// chmod cannot set the Unix exec bit on an NTFS/Windows host, so from a Windows
// box this only takes effect once the tree is packaged/extracted on the target
// OS — the warning makes that explicit. On a Linux/macOS host it fixes it outright.
function fixExecutableBits(outDir, verDir, osToken) {
  const targets = []
  if (osToken === 'macos') {
    // Everything in the app's MacOS dir is an executable (Blender + helpers).
    const macosDir = path.join(outDir, 'Blender.app', 'Contents', 'MacOS')
    if (fs.existsSync(macosDir)) {
      for (const e of fs.readdirSync(macosDir, { withFileTypes: true })) {
        if (e.isFile()) targets.push(path.join(macosDir, e.name))
      }
    }
  } else {
    // linux install tree: the binary, launcher and helpers live at the bin root.
    for (const n of ['blender', 'blender-launcher', 'blender-thumbnailer', 'blender-system-info.sh']) {
      targets.push(path.join(outDir, n))
    }
  }
  // The bundled Python interpreter under <ver>/python/bin also needs +x.
  const pyBin = path.join(verDir, 'python', 'bin')
  if (fs.existsSync(pyBin)) {
    for (const e of fs.readdirSync(pyBin, { withFileTypes: true })) {
      if (e.isFile() && /^python\d/.test(e.name)) targets.push(path.join(pyBin, e.name))
    }
  }
  let touched = 0
  for (const t of targets) {
    if (!fs.existsSync(t)) continue
    try { fs.chmodSync(t, 0o755); touched++ } catch (e) { warn(`chmod ${t}: ${e.message}`) }
  }
  if (process.platform === 'win32') {
    warn(`marked ${touched} ${osToken} binary/binaries executable, but an NTFS/Windows host cannot ` +
      `persist the Unix exec bit — run \`chmod +x\` on the target OS after transfer, or package the ` +
      `bundle on a ${osToken} runner for a launchable tree.`)
  } else {
    log(`restored +x on ${touched} ${osToken} binary/binaries`)
  }
}

// --- main ------------------------------------------------------------------

const USAGE = fs.readFileSync(fileURLToPath(import.meta.url), 'utf-8')
  .split('\n').filter((l) => l.startsWith(' * ')).map((l) => l.slice(3)).join('\n')

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  if (opts.help) { console.log(USAGE); return }

  if (!fs.existsSync(path.join(ADDON_SRC, '__init__.py'))) fail(`addon package missing at ${ADDON_SRC}`)
  if (!fs.existsSync(path.join(PKG_ROOT, '_capi.py'))) {
    fail(`engine ctypes package missing at ${PKG_ROOT} — run: git submodule update --init`)
  }
  if (capture('gh', ['--version'], { allowFail: true }).status !== 0) fail('the GitHub CLI (gh) is not on PATH')
  if (capture('gh', ['auth', 'status'], { allowFail: true }).status !== 0) fail('gh is not authenticated — run: gh auth login')

  // Repo discovery.
  const forkSlug = githubSlug(opts.blenderSrc, 'the Blender fork')
  const engineSlug = githubSlug(ENGINE, 'the engine submodule')
  const engineHead = capture('git', ['-C', ENGINE, 'rev-parse', 'HEAD']).stdout

  // Resolve the two source runs (shared across platforms).
  const blenderRun = resolveRun({
    slug: forkSlug, workflow: 'build.yml', label: 'blender',
    runId: opts.blenderRun, commit: opts.blenderCommit, branch: opts.blenderBranch,
  })
  const engineRun = resolveRun({
    slug: engineSlug, workflow: 'native-nightly.yml', label: 'engine',
    runId: opts.engineRun,
    commit: opts.engineCommit || (opts.engineLatest ? null : engineHead),
    branch: 'master',
  })

  log(`fork repo    : ${forkSlug}  (build.yml run ${blenderRun})`)
  log(`engine repo  : ${engineSlug}  (native-nightly.yml run ${engineRun})`)
  log(`engine commit: ${engineHead.slice(0, 12)}${opts.engineLatest ? ' (submodule; libs from --engine-latest)' : ' (submodule; libs pinned to match)'}`)
  log(`platforms    : ${opts.platforms.join(', ')}`)
  log(`config       : ${opts.config}`)
  log(`out          : ${opts.out}`)

  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'scdist-'))
  let bakedUserpref = null
  const hostOs = NODE_PLATFORM_TO_OS[process.platform]
  const summary = []

  try {
    for (const p of opts.platforms) {
      const osToken = OS_TOKENS[p]
      log(`\x1b[1m=== ${p} (${osToken}) ===\x1b[0m`)

      // 1. Download engine libs (small) to scratch; the Blender install tree
      //    (large — up to ~1.6 GB) extracts straight into the output dir, so we
      //    never copy the whole tree a second time.
      const libsDl = path.join(tmpRoot, `libs-${p}`)
      downloadArtifact({ slug: engineSlug, runId: engineRun, name: `sculptcore-libs-${osToken}-${opts.config}`, destDir: libsDl })

      const outDir = path.join(opts.out, p)
      log(`downloading install tree -> ${outDir}`)
      fs.rmSync(outDir, { recursive: true, force: true })
      downloadArtifact({ slug: forkSlug, runId: blenderRun, name: `blender-install-${osToken}`, destDir: outDir })

      // 3. Stage the addon (fresh; lib/ filled next). Blender 5.x only scans the
      //    versioned system path `scripts/addons_core` (addon_utils.paths()); the
      //    legacy `scripts/addons` is no longer searched in an install tree.
      const verDir = findVersionDir(outDir)
      const addonDst = path.join(verDir, 'scripts', 'addons_core', ADDON_MODULE)
      log(`staging addon -> ${addonDst}`)
      fs.rmSync(addonDst, { recursive: true, force: true })
      copyTree(ADDON_SRC, addonDst, new Set(['lib', '__pycache__', '.mypy_cache']))

      // 4. Vendor the ctypes package + fetched libs.
      log(`vendoring engine runtime (${p} libs + local ctypes package)…`)
      vendorRuntime(addonDst, libsDl, p)

      // 4b. Restore the executable bit lost by the artifact zip (non-Windows).
      if (p !== 'windows') fixExecutableBits(outDir, verDir, p)

      // 5. Enable-by-default: bake on host, copy to others.
      const configDir = path.join(verDir, 'config')
      let enabled = 'skipped'
      if (opts.enable) {
        if (p === hostOs) {
          ensureDir(configDir)
          const exe = process.platform === 'win32' ? 'blender.exe' : 'blender'
          const exePath = fs.existsSync(path.join(outDir, exe))
            ? path.join(outDir, exe)
            : findExe(outDir, exe)
          log(`baking enabled-by-default userpref via ${exePath}`)
          const status = run(exePath, ['--background', '--factory-startup', '--python', ENABLE_PY], { BLENDER_USER_CONFIG: configDir })
          if (status !== 0) fail(`enabling the addon failed (code ${status})`)
          bakedUserpref = path.join(configDir, 'userpref.blend')
          enabled = 'baked'
        } else {
          const src = bakedUserpref && fs.existsSync(bakedUserpref)
            ? bakedUserpref
            : findHostUserpref(opts.out, hostOs)
          if (src) {
            ensureDir(configDir)
            fs.copyFileSync(src, path.join(configDir, 'userpref.blend'))
            enabled = 'copied from host'
          } else {
            warn(`no host userpref to copy into ${p}; addon staged but not enabled by default ` +
              `(build the host platform too, or run Blender once and enable it manually)`)
          }
        }
      }
      summary.push({ p, outDir, enabled })
    }
  } finally {
    if (opts.keepTmp) log(`keeping scratch dir: ${tmpRoot}`)
    else fs.rmSync(tmpRoot, { recursive: true, force: true })
  }

  log(`\x1b[32mdone.\x1b[0m`)
  for (const s of summary) log(`  ${s.p}: ${s.outDir}  (userpref: ${s.enabled})`)
}

// Locate a Blender binary within an install tree (macOS: inside Blender.app).
function findExe(root, exe) {
  const stack = [root]
  while (stack.length) {
    const dir = stack.pop()
    let entries
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { continue }
    for (const e of entries) {
      const p = path.join(dir, e.name)
      if (e.isFile() && e.name === exe) return p
      if (e.isDirectory()) stack.push(p)
    }
  }
  fail(`no ${exe} found under ${root}`)
}

main().catch((e) => fail(e?.stack || String(e)))
