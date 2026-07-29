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
 * and mark the addon always-enabled.
 *
 * Version coordination (ABI): the ctypes `sculptcore` package is taken from the
 * `engine/` submodule at its checked-out commit, so the engine libs MUST come
 * from that same commit or engine.py's init() will refuse the mismatch.  The
 * engine artifact therefore defaults to the submodule HEAD and FAILS (rather
 * than silently drifting) if no CI run built it — override deliberately with
 * --engine-run / --engine-commit / --engine-latest.  The fork build has no such
 * constraint, so it defaults to the latest successful run.
 *
 * Enabling by default is a file, not a state: `.always_enable` next to the
 * staged addon, which the fork's addon_utils reads at startup (see
 * writeAlwaysEnable()).  It is written the same way for every platform, needs
 * no runnable Blender, and leaves the user's global config alone — the bundles
 * deliberately carry no user config of their own.  Only the *verification* pass
 * needs to run Blender, so it happens on the host platform alone.
 *
 * Permissions (why the Linux/macOS output is a .tar): GitHub's artifact zip
 * carries no Unix mode bits and no symlinks, so the fork's build.yml packs
 * those platforms' install trees into an uncompressed `blender-install.tar`
 * where both survive as entry metadata.  This tool must then get the addon
 * *into* that tree without unpacking it onto the host filesystem — on Windows
 * that round trip would drop the metadata again, leaving a `blender` binary
 * that will not launch.  So for a non-host platform it never extracts: it
 * stages the addon in a scratch dir and `tar -rf`-appends it, which leaves
 * every pre-existing entry byte-for-byte intact.  The deliverable is the .tar;
 * extract it on the target OS.  (Appended files are stored 0666/0777 from
 * NTFS, which a normal non-root `tar xf` masks down to 0644/0755 — they are
 * addon data, none of it needs the exec bit.)  The host platform is still
 * extracted to a real tree, so the bundle can be launched — and verified.
 * A Windows install artifact is a plain tree, having no metadata to lose.
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
 *   --engine-libs DIR   Use engine shared libraries already on disk instead of
 *                       downloading them.  Skips all engine run resolution, so
 *                       the ABI pin does not apply — the caller owns matching
 *                       the libs to the submodule's ctypes package.  This is
 *                       what the packaging CI uses: it builds the libs itself
 *                       (with brushes/ as extra kernel dirs) and points here.
 *   --blender-src DIR   Blender fork checkout, for repo discovery
 *                       (default: ../main, or $BLENDER_SRC).
 *   --blender-repo SLUG owner/name of the fork, instead of discovering it from
 *                       a local checkout.  For CI, which has no fork clone.
 *   --no-enable         Do not mark the addon always-enabled (it is then staged
 *                       but off until the user enables it in Preferences).
 *   --keep-tmp          Do not delete the per-run download scratch dir.
 *   -h, --help
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { vendorWindowsDeps } from './lib/windows-deps.mjs'

const TOOLS = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(TOOLS, '..')
const ENGINE = path.join(REPO, 'engine')
const ADDON_SRC = path.join(REPO, 'sculptcore_addon')
const VERIFY_PY = path.join(TOOLS, 'verify_addon.py')
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
    engineLibs: null,
    blenderSrc: process.env.BLENDER_SRC || path.resolve(REPO, '..', 'main'),
    blenderRepo: null,
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
      case '--engine-libs': opts.engineLibs = path.resolve(next()); break
      case '--blender-src': opts.blenderSrc = path.resolve(next()); break
      case '--blender-repo': opts.blenderRepo = next(); break
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
  // De-dupe, host first (the one platform whose bundle can be verified here).
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

// The tar to drive. On Windows, PATH commonly leads with msys/git-bash GNU tar,
// which reads `C:\...` as a remote host spec ("Cannot connect to C") — so go
// straight to the system bsdtar, which handles drive letters and supports the
// append (-r) this tool depends on.
function tarExe() {
  if (process.platform !== 'win32') return 'tar'
  return path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe')
}

// The version dir (e.g. `5.3`, or `Blender.app/Contents/Resources/5.3` on
// macOS) as a forward-slash path relative to the archive root, read from the
// entry listing so the tree never has to be extracted.
function findVersionDirInTar(tarPath) {
  const { stdout } = capture(tarExe(), ['-tf', tarPath])
  for (const line of stdout.split('\n')) {
    const m = /^(.*?\d+\.\d+)\/scripts\//.exec(line.trim().replace(/^\.\//, ''))
    if (m) return m[1]
  }
  fail(`could not locate a Blender <version>/scripts entry in ${tarPath}`)
}

// Mark the addon as always-enabled for a bundle, by writing `.always_enable`
// into the add-on directory the addon itself was staged into.
//
// The fork's addon_utils reads that file at startup and enables the modules it
// lists the way it enables its own hidden core add-ons: `default_set=False` (so
// nothing is written to the preferences) and `persistent=True` (so a
// preferences reload does not unload it).  The package therefore ships no user
// config at all — it reads and writes the machine's global Blender config, like
// any other install.  (The previous approach shipped a portable
// `userpref.blend`, which meant the package owned *every* user resource.)
function writeAlwaysEnable(addonsCoreDir, module) {
  const marker = path.join(addonsCoreDir, '.always_enable')
  fs.writeFileSync(marker, `# Add-ons this install always enables (Blender fork: addon_utils).\n${module}\n`)
  return marker
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
  // The libs dir doubles as a search path for dependencies to vendor: whatever
  // the build staged next to the engine libraries is the copy they were built
  // against.
  fixLibLinkage(dest, osToken, libsDir)
}

// Make the engine library self-contained: vendor every non-system dependency it
// records and rewrite the reference to point beside the loader.
//
// Windows is the same class of bug in its mildest form: the loader resolves
// imports by bare name and searches the loading DLL's own directory first (the
// ctypes load uses LOAD_WITH_ALTERED_SEARCH_PATH), so nothing needs rewriting —
// but the engine is a clang build and imports `libomp140.x86_64.dll`, which
// ships with Visual Studio / LLVM and *not* with the VC++ redistributable. On
// the builder it resolves out of System32 and the package looks fine; on a user
// machine without a toolchain the engine fails to load. So the import table is
// read and every non-system dependency copied in — see lib/windows-deps.mjs.
//
// The engine links against two libraries that live outside the standard search
// path — the prebuilt wgpu_native (in the engine's extern/ tree) and the
// toolchain's libomp — and the recorded references reach them by *build machine
// path*, so they resolve on the builder and nowhere else:
//
//   Linux  DT_NEEDED [/home/runner/.../extern/wgpu_native/lib/libwgpu_native.so]
//          DT_NEEDED [libomp.so.5] + RUNPATH [...:/usr/lib/llvm-18/lib]
//   macOS  LC_LOAD_DYLIB @rpath/libwgpu_native.dylib + LC_RPATH [/Users/runner/...]
//          LC_LOAD_DYLIB /opt/homebrew/opt/libomp/lib/libomp.dylib
//
// (wgpu_native has no SONAME/plain install name, which is why the absolute path
// gets baked in rather than a bare name.)  Colocating the libs is not enough —
// an absolute NEEDED, or a bare name only the build RUNPATH can satisfy, still
// points outside the package.  So copy each such dependency in and rewrite the
// reference to a bare name + $ORIGIN / @loader_path.
//
// Only possible where the tools exist (patchelf on Linux, install_name_tool on
// macOS); on any other host we cannot rewrite and say so.
function fixLibLinkage(dest, osToken, libsDir) {
  if (osToken === 'windows') {
    // Reading a PE import table needs no tools, but *resolving* a dependency
    // does need the machine that has it — staging a Windows bundle from Linux
    // or macOS cannot vendor anything.
    if (process.platform !== 'win32') {
      warn('cannot vendor the Windows engine dependencies from this host; package on a ' +
        'Windows runner, or the bundle will need libomp140.x86_64.dll already installed')
      return
    }
    const { missing } = vendorWindowsDeps(dest, { log, warn, searchDirs: libsDir ? [libsDir] : [] })
    if (missing.length) {
      fail(`missing Windows engine dependencies: ${missing.join(', ')} — the package would ` +
        `only load on a machine that already has them`)
    }
    return
  }
  const [capiName] = libNamesFor(osToken)
  const capi = path.join(dest, capiName)
  if (osToken === 'linux') relinkElf(capi, dest, capiName)
  else relinkMachO(capi, dest, capiName)
}

function relinkElf(capi, dest, capiName) {
  if (!hasTool('patchelf')) {
    warn(`patchelf not available; cannot rewrite ${capiName}'s linkage — the packaged engine ` +
      `will fail to load unless the build machine's paths exist on the target`)
    return
  }
  // The build RUNPATH doubles as the search list for the deps we must vendor;
  // it is dropped at the end, so read it before rewriting anything.
  const searchDirs = capture('patchelf', ['--print-rpath', capi], { allowFail: true })
    .stdout.split(':').map((s) => s.trim()).filter(Boolean)
  const needed = capture('patchelf', ['--print-needed', capi], { allowFail: true })
    .stdout.split('\n').map((s) => s.trim()).filter(Boolean)

  for (const n of needed) {
    const base = path.posix.basename(n)
    const isAbs = n !== base
    const dst = path.join(dest, base)
    if (!fs.existsSync(dst)) {
      // Not vendored yet. Absolute: take it verbatim. Bare name: only our
      // problem if the *build* RUNPATH is what satisfied it — anything the
      // system loader finds on its own (libc, libstdc++, …) has no entry there.
      const src = isAbs && fs.existsSync(n)
        ? n
        : searchDirs.map((d) => path.join(d, base)).find((f) => fs.existsSync(f))
      if (!src) {
        if (isAbs) warn(`${capiName} needs ${n}, which is not on this machine; cannot vendor it`)
        continue
      }
      fs.copyFileSync(src, dst)
      fs.chmodSync(dst, 0o755)
      log(`vendored dependency ${base}`)
    }
    run('patchelf', ['--set-soname', base, dst])
    if (isAbs) run('patchelf', ['--replace-needed', n, base, capi])
  }
  run('patchelf', ['--set-rpath', '$ORIGIN', capi])
  log(`relinked ${capiName} against its own directory ($ORIGIN rpath)`)
}

function relinkMachO(capi, dest, capiName) {
  if (!hasTool('install_name_tool')) {
    warn(`install_name_tool not available; cannot rewrite ${capiName}'s linkage — the packaged ` +
      `engine will fail to load unless the build machine's paths exist on the target`)
    return
  }
  // `otool -L` lists the load-dylib paths one per line after a header line.
  const deps = capture('otool', ['-L', capi], { allowFail: true })
    .stdout.split('\n').slice(1).map((l) => l.trim().split(' ')[0]).filter(Boolean)

  for (const n of deps) {
    if (!n.startsWith('/')) continue                    // already @rpath/@loader_path-relative
    if (/^\/(usr\/lib|System)\//.test(n)) continue      // OS libs, present everywhere
    const base = path.basename(n)
    const dst = path.join(dest, base)
    if (!fs.existsSync(dst)) {
      if (!fs.existsSync(n)) { warn(`${capiName} needs ${n}, which is not on this machine`); continue }
      fs.copyFileSync(n, dst)
      fs.chmodSync(dst, 0o755)
      log(`vendored dependency ${base}`)
    }
    run('install_name_tool', ['-id', `@rpath/${base}`, dst])
    resignAdHoc(dst)
    run('install_name_tool', ['-change', n, `@rpath/${base}`, capi])
  }
  // Drop the build machine's rpaths and look beside ourselves instead.
  // `otool -l` prints LC_RPATH as three lines; the third is `path <p> (offset N)`.
  const cmds = capture('otool', ['-l', capi], { allowFail: true }).stdout
  for (const m of cmds.matchAll(/LC_RPATH[\s\S]{0,120}?\n\s*path (.+?) \(offset \d+\)/g)) {
    run('install_name_tool', ['-delete_rpath', m[1], capi])
  }
  run('install_name_tool', ['-add_rpath', '@loader_path', capi])
  resignAdHoc(capi)
  log(`relinked ${capiName} against its own directory (@loader_path rpath)`)
}

// Editing load commands voids the existing signature, and arm64 refuses to load
// an invalidly-signed image outright — so re-sign ad-hoc after every rewrite.
function resignAdHoc(lib) {
  if (hasTool('codesign')) run('codesign', ['--force', '--sign', '-', lib])
}

function hasTool(name) {
  const probe = process.platform === 'win32' ? 'where' : 'which'
  return capture(probe, [name], { allowFail: true }).status === 0
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

  if (opts.engineLibs && !fs.existsSync(opts.engineLibs)) fail(`--engine-libs dir not found: ${opts.engineLibs}`)

  // Repo discovery. --blender-repo skips the fork checkout (CI has none);
  // --engine-libs skips the engine side entirely, libs being already on disk.
  const forkSlug = opts.blenderRepo || githubSlug(opts.blenderSrc, 'the Blender fork')
  const engineSlug = opts.engineLibs ? null : githubSlug(ENGINE, 'the engine submodule')
  const engineHead = capture('git', ['-C', ENGINE, 'rev-parse', 'HEAD'], { allowFail: true }).stdout

  // Resolve the source run(s). Shared across platforms.
  const blenderRun = resolveRun({
    slug: forkSlug, workflow: 'build.yml', label: 'blender',
    runId: opts.blenderRun, commit: opts.blenderCommit, branch: opts.blenderBranch,
  })
  const engineRun = opts.engineLibs ? null : resolveRun({
    slug: engineSlug, workflow: 'native-nightly.yml', label: 'engine',
    runId: opts.engineRun,
    commit: opts.engineCommit || (opts.engineLatest ? null : engineHead),
    branch: 'master',
  })

  log(`fork repo    : ${forkSlug}  (build.yml run ${blenderRun})`)
  if (opts.engineLibs) {
    log(`engine libs  : ${opts.engineLibs}  (prebuilt on disk; no ABI pin enforced)`)
  } else {
    log(`engine repo  : ${engineSlug}  (native-nightly.yml run ${engineRun})`)
  }
  log(`engine commit: ${engineHead.slice(0, 12) || '(unknown)'}${opts.engineLibs ? ' (submodule; ctypes package source)' : opts.engineLatest ? ' (submodule; libs from --engine-latest)' : ' (submodule; libs pinned to match)'}`)
  log(`platforms    : ${opts.platforms.join(', ')}`)
  log(`config       : ${opts.config}`)
  log(`out          : ${opts.out}`)

  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'scdist-'))
  const hostOs = NODE_PLATFORM_TO_OS[process.platform]
  const summary = []

  try {
    for (const p of opts.platforms) {
      const osToken = OS_TOKENS[p]
      log(`\x1b[1m=== ${p} (${osToken}) ===\x1b[0m`)

      // 1. Download engine libs (small) to scratch; the Blender install tree
      //    (large — up to ~1.6 GB) extracts straight into the output dir, so we
      //    never copy the whole tree a second time.
      let libsDl = opts.engineLibs
      if (!libsDl) {
        libsDl = path.join(tmpRoot, `libs-${p}`)
        downloadArtifact({ slug: engineSlug, runId: engineRun, name: `sculptcore-libs-${osToken}-${opts.config}`, destDir: libsDl })
      }

      const outDir = path.join(opts.out, p)
      log(`downloading install tree -> ${outDir}`)
      fs.rmSync(outDir, { recursive: true, force: true })
      downloadArtifact({ slug: forkSlug, runId: blenderRun, name: `blender-install-${osToken}`, destDir: outDir })

      // 2. Linux/macOS artifacts are a single uncompressed tar (it is the only
      //    way mode bits and symlinks survive GitHub's artifact zip); Windows
      //    and pre-tar runs are a plain tree. On the host we extract either
      //    way — the result is a launchable tree (which is what the verify pass
      //    needs) and the host OS applies the archived metadata correctly.
      const tarPath = path.join(outDir, 'blender-install.tar')
      const wasTar = fs.existsSync(tarPath)
      let isTar = wasTar
      if (isTar && p === hostOs) {
        log(`extracting install tar (host platform)…`)
        if (run(tarExe(), ['-xf', tarPath, '-C', outDir]) !== 0) fail(`extracting ${tarPath} failed`)
        fs.rmSync(tarPath)
        isTar = false
      }

      // 2b. Non-host tar: stage the addon in scratch and append it, so nothing
      //     already in the archive is rewritten. See the header note.
      if (isTar) {
        const relVer = findVersionDirInTar(tarPath)
        const stage = path.join(tmpRoot, `stage-${p}`)
        fs.rmSync(stage, { recursive: true, force: true })
        const addonDst = path.join(stage, ...relVer.split('/'), 'scripts', 'addons_core', ADDON_MODULE)
        log(`staging addon -> ${relVer}/scripts/addons_core/${ADDON_MODULE} (in ${tarPath})`)
        copyTree(ADDON_SRC, addonDst, new Set(['lib', '__pycache__', '.mypy_cache']))
        log(`vendoring engine runtime (${p} libs + local ctypes package)…`)
        vendorRuntime(addonDst, libsDl, p)

        const addonsCore = `${relVer}/scripts/addons_core`
        const members = [`./${addonsCore}/${ADDON_MODULE}`]
        let enabled = 'skipped'
        if (opts.enable) {
          writeAlwaysEnable(path.dirname(addonDst), ADDON_MODULE)
          members.push(`./${addonsCore}/.always_enable`)
          enabled = 'marked'
        }
        if (run(tarExe(), ['-rf', tarPath, '-C', stage, ...members]) !== 0) {
          fail(`appending the addon to ${tarPath} failed`)
        }
        log(`extract on the target OS to get a launchable tree: tar -xf blender-install.tar`)
        summary.push({ p, outDir: tarPath, enabled })
        continue
      }

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
      //     Only for a pre-tar tree artifact — a tar we extracted above already
      //     carried the real modes, and this is the host OS, so they applied.
      if (p !== 'windows' && !wasTar) fixExecutableBits(outDir, verDir, p)

      // 5. Enable-by-default: the marker file, then (host only) prove it by
      //    launching the bundle. --factory-startup makes the check independent
      //    of whatever is in this machine's global Blender config.
      let enabled = 'skipped'
      if (opts.enable) {
        const marker = writeAlwaysEnable(path.dirname(addonDst), ADDON_MODULE)
        log(`marking always-enabled -> ${marker}`)
        enabled = 'marked'
        if (p === hostOs) {
          // macOS names the bundle executable `Blender`, not `blender`.
          const exes = process.platform === 'win32' ? ['blender.exe']
            : process.platform === 'darwin' ? ['Blender', 'blender'] : ['blender']
          const direct = exes.map((e) => path.join(outDir, e)).find((f) => fs.existsSync(f))
          const exePath = direct || findExe(outDir, exes)
          log(`verifying enabled-by-default via ${exePath}`)
          const status = run(exePath, ['--background', '--factory-startup', '--python', VERIFY_PY])
          if (status !== 0) {
            fail('the addon did not come up enabled — does this fork build carry the ' +
              '.always_enable support in scripts/modules/addon_utils.py?')
          }
          enabled = 'marked + verified'
        }
      }
      summary.push({ p, outDir, enabled })
    }
  } finally {
    if (opts.keepTmp) log(`keeping scratch dir: ${tmpRoot}`)
    else fs.rmSync(tmpRoot, { recursive: true, force: true })
  }

  log(`\x1b[32mdone.\x1b[0m`)
  for (const s of summary) log(`  ${s.p}: ${s.outDir}  (enabled by default: ${s.enabled})`)
}

// Locate a Blender binary within an install tree, trying each candidate name
// (macOS keeps it at Blender.app/Contents/MacOS/Blender — capital B).
function findExe(root, exes) {
  const wanted = new Set(exes)
  const stack = [root]
  while (stack.length) {
    const dir = stack.pop()
    let entries
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { continue }
    for (const e of entries) {
      const p = path.join(dir, e.name)
      if (e.isFile() && wanted.has(e.name)) return p
      if (e.isDirectory()) stack.push(p)
    }
  }
  fail(`no ${exes.join(' or ')} found under ${root}`)
}

main().catch((e) => fail(e?.stack || String(e)))
