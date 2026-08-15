// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/*
 * build-blender-dist.mjs — assemble a runnable Blender install with the
 * SculptCore sculpt mode bundled and enabled by default.
 *
 * Chain:
 *   1. Build the Blender fork (custom-object-modes) INSTALL target.  Its
 *      Windows `bin/` tree *is* a portable Blender.
 *   2. Optionally mirror that tree into a clean `--dist <dir>` (else stage
 *      in place in the build's `bin/`).
 *   3. Copy the addon package into `<install>/<ver>/scripts/addons_core/`.
 *   4. Vendor the engine runtime (ctypes package + DLLs) into the addon's
 *      `lib/` via the engine's own `make.mjs bundle` (builds the DLL too).
 *   5. Write `<install>/<ver>/scripts/addons_core/.always_enable`, which the
 *      fork's addon_utils reads at startup, and verify it headlessly.  The
 *      install has no user config of its own: it uses the machine's global
 *      Blender config, which this leaves untouched.
 *
 * No npm dependencies — plain Node.  Windows-first (the engine and fork are
 * developed on Windows); the copy step uses robocopy there, `cp -a` elsewhere.
 *
 * Usage:
 *   node tools/build-blender-dist.mjs [options]
 *
 *   --blender-src DIR   Blender fork checkout (default: ../main, or $BLENDER_SRC)
 *   --build-dir DIR     Blender build tree to install from
 *                       (default: autodetect ../build_*_<config> beside the fork)
 *   --config CFG        Build config keyword for autodetect (default: RelWithDebInfo)
 *   --dist DIR          Mirror the install tree here first (clean distributable).
 *                       Omit to stage in place in <build-dir>/bin.
 *   --skip-blender      Do not (re)build Blender; use the existing bin/ tree.
 *   --skip-engine       Do not rebuild the engine DLL; restage existing outputs.
 *   --run               Launch the finished install at the end (smoke check).
 *   -h, --help
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { vendorWindowsDeps } from './lib/windows-deps.mjs'

const TOOLS = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(TOOLS, '..')
const ENGINE = path.join(REPO, 'engine')
const ADDON_SRC = path.join(REPO, 'sculptcore_addon')
const VERIFY_PY = path.join(TOOLS, 'verify_addon.py')
const ADDON_MODULE = 'sculptcore_addon'
// Other addons this repo ships. Plain Python packages: staged the same way and
// enabled by the same marker, but with no engine runtime vendored into them.
const EXTRA_ADDON_MODULES = ['brush_save_reminder']
const EXE =process.platform === 'win32' ? 'blender.exe' : 'blender'

// --- tiny arg parser -------------------------------------------------------

function parseArgs(argv) {
  const opts = {
    blenderSrc: process.env.BLENDER_SRC || path.resolve(REPO, '..', 'main'),
    buildDir: null,
    config: 'RelWithDebInfo',
    dist: null,
    skipBlender: false,
    skipEngine: false,
    run: false,
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    switch (a) {
      case '--blender-src': opts.blenderSrc = path.resolve(next()); break
      case '--build-dir': opts.buildDir = path.resolve(next()); break
      case '--config': opts.config = next(); break
      case '--dist': opts.dist = path.resolve(next()); break
      case '--skip-blender': opts.skipBlender = true; break
      case '--skip-engine': opts.skipEngine = true; break
      case '--run': opts.run = true; break
      case '-h': case '--help': opts.help = true; break
      default:
        fail(`unknown option: ${a} (try --help)`)
    }
  }
  return opts
}

// --- helpers ---------------------------------------------------------------

function log(msg) { console.log(`\x1b[36m[dist]\x1b[0m ${msg}`) }
function warn(msg) { console.error(`\x1b[33m[dist] warn:\x1b[0m ${msg}`) }
function fail(msg) { console.error(`\x1b[31m[dist] error:\x1b[0m ${msg}`); process.exit(1) }

function run(cmd, args, cwd, extraEnv, shell = false) {
  log(`$ ${cmd} ${args.join(' ')}${cwd ? `   (in ${cwd})` : ''}`)
  const res = spawnSync(cmd, args, {
    cwd,
    stdio: 'inherit',
    env: extraEnv ? { ...process.env, ...extraEnv } : process.env,
    // node/cmake/robocopy resolve from PATH directly; package managers such as
    // pnpm are .cmd shims on Windows and need a shell to be found (shell=true).
    shell,
  })
  if (res.error) fail(`failed to launch ${cmd}: ${res.error.message}`)
  return res.status ?? 0
}

function ensureDir(d) { fs.mkdirSync(d, { recursive: true }) }

// Mark the addon as always-enabled for this install.
//
// The fork's addon_utils reads `.always_enable` from each add-on directory at
// startup and enables the modules it lists the way it enables its own hidden
// core add-ons: `default_set=False` (never written to the preferences) and
// `persistent=True` (a preferences reload does not unload it). So the install
// is sculpt-mode-by-default while reading and writing the user's *global*
// config like any other Blender — no portable config, no baked userpref.
function writeAlwaysEnable(addonsCoreDir, modules) {
  const marker = path.join(addonsCoreDir, '.always_enable')
  const lines = [].concat(modules).map((m) => `${m}\n`).join('')
  fs.writeFileSync(marker, `# Add-ons this install always enables (Blender fork: addon_utils).\n${lines}`)
  return marker
}

// Remove a `portable/` directory left by an older revision of this script.
//
// Blender 5.x treats an install as portable when a directory literally named
// `portable` sits beside the executable (appdir.cc get_path_user_ex), and then
// resolves *every* user resource under it — config, scripts, extensions,
// datafiles. A leftover one therefore silently keeps this install away from the
// global config, which is the whole point of the `.always_enable` marker. It is
// a build product of this script (an enabled-by-default userpref, plus whatever
// Blender wrote beside it), so it goes wholesale — logged, not silently.
function removeStalePortableDir(installDir) {
  const portable = path.join(installDir, 'portable')
  if (!fs.existsSync(portable)) return
  const listed = []
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else listed.push(path.relative(portable, p))
    }
  }
  walk(portable)
  log(`removing stale portable config dir ${portable} (${listed.join(', ') || 'empty'})`)
  log('  this install now uses the machine-wide Blender config')
  fs.rmSync(portable, { recursive: true, force: true })
}

// Recursively copy src -> dst, skipping directory names in `skip`.
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

// Mirror srcDir -> dstDir (dst becomes an exact copy). robocopy on win32.
function mirror(srcDir, dstDir) {
  ensureDir(dstDir)
  if (process.platform === 'win32') {
    const status = run('robocopy', [srcDir, dstDir, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1'])
    // robocopy: exit codes < 8 are success (bit flags for copied/extra/etc.).
    if (status >= 8) fail(`robocopy failed mirroring ${srcDir} -> ${dstDir} (code ${status})`)
  } else {
    run('rm', ['-rf', dstDir])
    run('cp', ['-a', srcDir, dstDir])
  }
}

// Locate the numeric <major.minor> resource dir by asking Blender itself.
function blenderVersionDir(installDir) {
  const exe = path.join(installDir, EXE)
  if (!fs.existsSync(exe)) fail(`no ${EXE} in ${installDir}`)
  const res = spawnSync(exe, ['--version'], { encoding: 'utf-8' })
  const m = /Blender\s+(\d+)\.(\d+)/.exec(`${res.stdout || ''}${res.stderr || ''}`)
  if (!m) fail(`could not parse 'blender --version' output`)
  const ver = `${m[1]}.${m[2]}`
  const dir = path.join(installDir, ver)
  if (!fs.existsSync(path.join(dir, 'scripts'))) fail(`no ${ver}/scripts under ${installDir}`)
  return ver
}

// One-time engine setup that a fresh clone lacks: nested submodules, the pnpm
// workspace, and the wgpu-native prebuilt. Each check is a no-op once satisfied,
// so the steady-state cost is a few fs.existsSync calls. Everything here is the
// engine's own; we drive it through the engine's tooling, never reimplement it.
function ensureEngineReady() {
  // Submodules (imgui.cpp is the canonical missing-source symptom; litestl holds
  // the pnpm workspace member @litestl/typescript-runtime).
  if (!fs.existsSync(path.join(ENGINE, 'extern', 'imgui', 'imgui.cpp'))) {
    log('engine submodules missing — git submodule update --init…')
    if (run('git', ['submodule', 'update', '--init'], ENGINE) !== 0) {
      fail('engine submodule checkout failed')
    }
  }
  // pnpm workspace (make.mjs itself imports node deps; node_modules must exist).
  if (!fs.existsSync(path.join(ENGINE, 'node_modules'))) {
    log('engine node_modules missing — pnpm install…')
    if (run('pnpm', ['install'], ENGINE, undefined, process.platform === 'win32') !== 0) {
      fail('engine pnpm install failed')
    }
  }
  // wgpu-native prebuilt (not checked in; the engine has its own fetch target).
  if (!fs.existsSync(path.join(ENGINE, 'extern', 'wgpu_native', 'include', 'webgpu', 'webgpu.h'))) {
    log('wgpu-native prebuilt missing — node make.mjs fetch-wgpu-native…')
    if (run('node', ['make.mjs', 'fetch-wgpu-native'], ENGINE) !== 0) {
      fail('wgpu-native fetch failed')
    }
  }
}

// Autodetect ../build_*_<config> beside the fork, preferring clang, newest.
function autodetectBuildDir(blenderSrc, config) {
  const parent = path.dirname(path.resolve(blenderSrc))
  const cfg = config.toLowerCase()
  const cands = fs.readdirSync(parent, { withFileTypes: true })
    .filter((e) => e.isDirectory() && e.name.startsWith('build_') && e.name.toLowerCase().includes(cfg))
    .map((e) => path.join(parent, e.name))
    .filter((d) => fs.existsSync(path.join(d, 'bin', EXE)))
    .sort((a, b) => {
      const clang = (p) => (p.toLowerCase().includes('clang') ? 1 : 0)
      if (clang(b) !== clang(a)) return clang(b) - clang(a)
      return fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs
    })
  if (!cands.length) {
    fail(`no build tree matching *${config}* with ${EXE} beside ${blenderSrc}; pass --build-dir`)
  }
  return cands[0]
}

// --- main ------------------------------------------------------------------

const USAGE = fs.readFileSync(fileURLToPath(import.meta.url), 'utf-8')
  .split('\n').filter((l) => l.startsWith(' * ')).map((l) => l.slice(3)).join('\n')

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  if (opts.help) { console.log(USAGE); return }

  if (!fs.existsSync(path.join(ADDON_SRC, '__init__.py'))) fail(`addon package missing at ${ADDON_SRC}`)
  for (const module of EXTRA_ADDON_MODULES) {
    if (!fs.existsSync(path.join(REPO, module, '__init__.py'))) {
      fail(`addon package missing at ${path.join(REPO, module)}`)
    }
  }
  if (!fs.existsSync(path.join(ENGINE, 'make.mjs'))) {
    fail(`engine submodule missing at ${ENGINE} — run: git submodule update --init`)
  }

  const buildDir = opts.buildDir || autodetectBuildDir(opts.blenderSrc, opts.config)
  log(`blender fork : ${opts.blenderSrc}`)
  log(`build tree   : ${buildDir}`)

  // 1. Build Blender (INSTALL populates bin/).
  if (!opts.skipBlender) {
    log('building Blender (install target)…')
    const status = run('cmake', ['--build', buildDir, '--target', 'install', '--config', opts.config])
    if (status !== 0) fail(`Blender build failed (code ${status})`)
  } else {
    log('skipping Blender build (--skip-blender)')
  }

  const binDir = path.join(buildDir, 'bin')
  if (!fs.existsSync(path.join(binDir, EXE))) fail(`no ${EXE} in ${binDir} — build Blender first`)

  // 2. Choose the install folder: clean --dist copy, or the build's bin/ in place.
  let installDir = binDir
  if (opts.dist) {
    log(`mirroring install tree -> ${opts.dist}`)
    mirror(binDir, opts.dist)
    installDir = opts.dist
  } else {
    log(`staging in place: ${binDir}`)
  }

  const ver = blenderVersionDir(installDir)
  log(`blender version dir: ${ver}`)

  // 3. Stage the addon package (fresh; lib/ is filled by the engine bundle).
  //    Blender 5.x only scans the versioned system path `scripts/addons_core`
  //    (addon_utils.paths()); the legacy `scripts/addons` is no longer searched,
  //    so an addon staged there fails to enable ("No module named ...").
  const addonDst = path.join(installDir, ver, 'scripts', 'addons_core', ADDON_MODULE)
  log(`staging addon -> ${addonDst}`)
  fs.rmSync(addonDst, { recursive: true, force: true })
  copyTree(ADDON_SRC, addonDst, new Set(['lib', '__pycache__', '.mypy_cache']))

  for (const module of EXTRA_ADDON_MODULES) {
    const dst = path.join(path.dirname(addonDst), module)
    log(`staging addon -> ${dst}`)
    fs.rmSync(dst, { recursive: true, force: true })
    copyTree(path.join(REPO, module), dst, new Set(['__pycache__', '.mypy_cache']))
  }

  // 4. Vendor the engine runtime into the addon's lib/ (builds the DLL too,
  //    unless --skip-engine). `bundle <dir>` stages into <dir>/sculptcore.
  ensureEngineReady()
  const libDest = path.join(addonDst, 'lib')
  ensureDir(libDest)
  const bundleArgs = ['make.mjs', 'bundle', libDest]
  if (opts.skipEngine) bundleArgs.push('--no-build')
  // Repo-carried extra sbrush kernels (<repo>/brushes/*.sbrush) compile into
  // the DLL alongside the built-ins — build-time sources, deliberately outside
  // sculptcore_addon/ (which is copied verbatim into installs).
  const brushesDir = path.join(REPO, 'brushes')
  const hasExtraKernels =
    fs.existsSync(brushesDir) && fs.readdirSync(brushesDir).some((f) => f.endsWith('.sbrush'))
  if (hasExtraKernels) {
    bundleArgs.push('--kernels-extra', brushesDir)
    if (opts.skipEngine) {
      log('note: brushes/ has extra kernels but --skip-engine is set; the restaged DLL may lack them')
    }
  } else {
    // Explicitly none — clears a previously configured extras dir instead of
    // silently keeping it in the engine's build cache.
    bundleArgs.push('--kernels-extra=')
  }
  log(`vendoring engine runtime${opts.skipEngine ? ' (restage only)' : ' (build + stage)'}…`)
  const bundleStatus = run('node', bundleArgs, ENGINE)
  if (bundleStatus !== 0) fail(`engine bundle failed (code ${bundleStatus})`)

  // 4b. Copy in the toolchain DLLs the engine imports (clang's OpenMP runtime),
  //     which System32 would otherwise satisfy here and nowhere else. A dev
  //     install is the thing sculpting actually gets tested in, so it should be
  //     as self-contained as a shipped package — see lib/windows-deps.mjs.
  if (process.platform === 'win32') {
    const { missing } = vendorWindowsDeps(path.join(libDest, 'sculptcore'), { log, warn })
    if (missing.length) warn(`unresolved engine dependencies: ${missing.join(', ')}`)
  }

  // 5. Enable by default, without owning the user config: drop the marker the
  //    fork's addon_utils reads at startup, then prove it headlessly.
  //    --factory-startup means the check owes nothing to any userpref.
  removeStalePortableDir(installDir)
  const marker = writeAlwaysEnable(path.dirname(addonDst), [ADDON_MODULE, ...EXTRA_ADDON_MODULES])
  log(`marking always-enabled -> ${marker}`)
  const verifyStatus = run(
    path.join(installDir, EXE),
    ['--background', '--factory-startup', '--python', VERIFY_PY],
  )
  if (verifyStatus !== 0) {
    fail('the addon did not come up enabled — is this a fork build with the ' +
      '.always_enable support in scripts/modules/addon_utils.py?')
  }

  log(`\x1b[32mdone.\x1b[0m install ready at: ${installDir}`)
  log(`launch: "${path.join(installDir, EXE)}"`)

  if (opts.run) {
    log('launching (smoke)…')
    run(path.join(installDir, EXE), [])
  }
}

main().catch((e) => fail(e?.stack || String(e)))
