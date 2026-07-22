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
 *   3. Copy the addon package into `<install>/<ver>/scripts/addons/`.
 *   4. Vendor the engine runtime (ctypes package + DLLs) into the addon's
 *      `lib/` via the engine's own `make.mjs bundle` (builds the DLL too).
 *   5. Run Blender headless to enable the addon and save a portable
 *      `<install>/<ver>/config/userpref.blend`, so it is on by default.
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

const TOOLS = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(TOOLS, '..')
const ENGINE = path.join(REPO, 'engine')
const ADDON_SRC = path.join(REPO, 'sculptcore_addon')
const ENABLE_PY = path.join(TOOLS, 'enable_addon.py')
const ADDON_MODULE = 'sculptcore_addon'
const EXE = process.platform === 'win32' ? 'blender.exe' : 'blender'

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
function fail(msg) { console.error(`\x1b[31m[dist] error:\x1b[0m ${msg}`); process.exit(1) }

function run(cmd, args, cwd, extraEnv) {
  log(`$ ${cmd} ${args.join(' ')}${cwd ? `   (in ${cwd})` : ''}`)
  const res = spawnSync(cmd, args, {
    cwd,
    stdio: 'inherit',
    env: extraEnv ? { ...process.env, ...extraEnv } : process.env,
    // node/cmake/robocopy are resolved from PATH; no shell needed.
  })
  if (res.error) fail(`failed to launch ${cmd}: ${res.error.message}`)
  return res.status ?? 0
}

function ensureDir(d) { fs.mkdirSync(d, { recursive: true }) }

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
  const addonDst = path.join(installDir, ver, 'scripts', 'addons', ADDON_MODULE)
  log(`staging addon -> ${addonDst}`)
  fs.rmSync(addonDst, { recursive: true, force: true })
  copyTree(ADDON_SRC, addonDst, new Set(['lib', '__pycache__', '.mypy_cache']))

  // 4. Vendor the engine runtime into the addon's lib/ (builds the DLL too,
  //    unless --skip-engine). `bundle <dir>` stages into <dir>/sculptcore.
  const libDest = path.join(addonDst, 'lib')
  ensureDir(libDest)
  const bundleArgs = ['make.mjs', 'bundle', libDest]
  if (opts.skipEngine) bundleArgs.push('--no-build')
  log(`vendoring engine runtime${opts.skipEngine ? ' (restage only)' : ' (build + stage)'}…`)
  const bundleStatus = run('node', bundleArgs, ENGINE)
  if (bundleStatus !== 0) fail(`engine bundle failed (code ${bundleStatus})`)

  // 5. Enable by default: save a portable userpref.blend in <install>/<ver>/config.
  const configDir = path.join(installDir, ver, 'config')
  ensureDir(configDir)
  log(`generating enabled-by-default userpref -> ${path.join(configDir, 'userpref.blend')}`)
  const enableStatus = run(
    path.join(installDir, EXE),
    ['--background', '--factory-startup', '--python', ENABLE_PY],
    undefined,
    { BLENDER_USER_CONFIG: configDir },
  )
  if (enableStatus !== 0) fail(`enabling the addon failed (code ${enableStatus})`)

  log(`\x1b[32mdone.\x1b[0m install ready at: ${installDir}`)
  log(`launch: "${path.join(installDir, EXE)}"`)

  if (opts.run) {
    log('launching (smoke)…')
    run(path.join(installDir, EXE), [])
  }
}

main().catch((e) => fail(e?.stack || String(e)))
