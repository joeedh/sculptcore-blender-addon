// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/*
 * windows-deps.mjs — make a staged Windows engine runtime self-contained, the
 * way `relinkElf()` / `relinkMachO()` do for the other two platforms.
 *
 * PE needs no *relinking* — the loader resolves imports by bare name, and
 * ctypes loads `sculptcore_capi.dll` with LOAD_WITH_ALTERED_SEARCH_PATH, so the
 * DLL's own directory is searched before System32.  What it does need is the
 * dependencies to actually BE there.  The engine is a clang build, so it
 * imports the LLVM OpenMP runtime (`libomp140.x86_64.dll`), which ships with
 * Visual Studio / LLVM and NOT with the VC++ redistributable: on a build
 * machine it resolves out of System32 and everything looks fine, while a user
 * without a toolchain installed gets a load failure.
 *
 * So: read what the staged DLLs import, copy in every non-system dependency
 * that is missing (following the ones just copied, since they have imports of
 * their own), and report anything unresolvable.
 *
 * The import table is parsed here rather than shelled out to `dumpbin`, which
 * lives in a Visual Studio install and is absent from a plain runner.
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

// Imports the OS or the VC++ redistributable provides.  Everything else is the
// engine's own problem and gets vendored.  (Blender itself requires the VC
// redist and ships the runtime DLLs beside its executable.)
const SYSTEM_PREFIXES = ['api-ms-win-', 'ext-ms-win-']
const SYSTEM_DLLS = new Set([
  // Core Win32.
  'ntdll.dll', 'kernel32.dll', 'kernelbase.dll', 'kernel.appcore.dll', 'user32.dll',
  'gdi32.dll', 'gdi32full.dll', 'advapi32.dll', 'sechost.dll', 'rpcrt4.dll',
  'shell32.dll', 'shlwapi.dll', 'shcore.dll', 'windows.storage.dll', 'combase.dll',
  'ole32.dll', 'oleaut32.dll', 'oleacc.dll', 'comdlg32.dll', 'comctl32.dll',
  'setupapi.dll', 'cfgmgr32.dll', 'version.dll', 'winmm.dll', 'imm32.dll',
  'powrprof.dll', 'userenv.dll', 'propsys.dll', 'psapi.dll', 'dbghelp.dll',
  'crypt32.dll', 'bcrypt.dll', 'bcryptprimitives.dll', 'ncrypt.dll', 'secur32.dll',
  'wintrust.dll', 'normaliz.dll', 'cabinet.dll', 'hid.dll', 'avrt.dll',
  // Networking.
  'ws2_32.dll', 'wsock32.dll', 'mswsock.dll', 'iphlpapi.dll', 'dnsapi.dll',
  'netapi32.dll', 'winhttp.dll', 'wininet.dll',
  // Graphics / media (wgpu_native reaches for these).
  'd3d11.dll', 'd3d12.dll', 'dxgi.dll', 'd3dcompiler_47.dll', 'dxva2.dll',
  'opengl32.dll', 'glu32.dll', 'dwmapi.dll', 'uxtheme.dll', 'mfplat.dll',
  'xinput1_4.dll',
  // CRT + VC++ redistributable.
  'msvcrt.dll', 'ucrtbase.dll', 'ucrtbased.dll',
  'vcruntime140.dll', 'vcruntime140_1.dll', 'vcruntime140d.dll', 'vcruntime140_1d.dll',
  'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140d.dll',
  'msvcp140_atomic_wait.dll', 'concrt140.dll',
])

function isSystemDll(name) {
  const lower = name.toLowerCase()
  return SYSTEM_DLLS.has(lower) || SYSTEM_PREFIXES.some((p) => lower.startsWith(p))
}

function readCString(buf, off) {
  if (off < 0 || off >= buf.length) return null
  const end = buf.indexOf(0, off)
  return buf.toString('latin1', off, end === -1 ? buf.length : end)
}

/**
 * The DLL names a PE image imports, from both the ordinary import directory and
 * the delay-load one (the engine's wgpu_native reference is delay-loaded, so
 * skipping the latter would miss it).  Returns [] for anything that is not a
 * readable PE image.
 */
export function peImports(file) {
  let buf
  try { buf = fs.readFileSync(file) } catch { return [] }
  if (buf.length < 0x40 || buf.readUInt16LE(0) !== 0x5a4d) return []  // 'MZ'

  const peOff = buf.readUInt32LE(0x3c)
  if (buf.length < peOff + 24 || buf.readUInt32LE(peOff) !== 0x00004550) return []  // 'PE\0\0'

  const numSections = buf.readUInt16LE(peOff + 6)
  const optSize = buf.readUInt16LE(peOff + 20)
  const optOff = peOff + 24
  if (buf.length < optOff + optSize) return []
  // PE32+ (0x20b) puts the data directories 16 bytes further in than PE32.
  const dirOff = optOff + (buf.readUInt16LE(optOff) === 0x20b ? 112 : 96)

  const sections = []
  for (let i = 0; i < numSections; i++) {
    const s = optOff + optSize + i * 40
    if (s + 40 > buf.length) break
    sections.push({
      va: buf.readUInt32LE(s + 12),
      vsize: buf.readUInt32LE(s + 8),
      rawSize: buf.readUInt32LE(s + 16),
      raw: buf.readUInt32LE(s + 20),
    })
  }
  const toOffset = (rva) => {
    for (const s of sections) {
      const size = Math.max(s.vsize, s.rawSize)
      if (rva >= s.va && rva < s.va + size) return s.raw + (rva - s.va)
    }
    return -1
  }
  const dirRva = (index) => {
    const at = dirOff + index * 8
    return at + 8 <= buf.length ? buf.readUInt32LE(at) : 0
  }

  const names = []
  // Import directory (index 1): IMAGE_IMPORT_DESCRIPTOR[], 20 bytes each, name
  // RVA at +12, terminated by an all-zero descriptor.
  for (let off = toOffset(dirRva(1)); off > 0 && off + 20 <= buf.length; off += 20) {
    const nameRva = buf.readUInt32LE(off + 12)
    if (!nameRva && !buf.readUInt32LE(off)) break
    const name = readCString(buf, toOffset(nameRva))
    if (name) names.push(name)
  }
  // Delay-load directory (index 13): ImgDelayDescr[], 32 bytes each, name RVA
  // at +4. Pre-VS2015 linkers stored virtual addresses here rather than RVAs;
  // those simply fail to map to a section and are skipped.
  for (let off = toOffset(dirRva(13)); off > 0 && off + 32 <= buf.length; off += 32) {
    const nameRva = buf.readUInt32LE(off + 4)
    if (!nameRva) break
    const name = readCString(buf, toOffset(nameRva))
    if (name) names.push(name)
  }
  return [...new Set(names)]
}

function whichAll(exe) {
  const res = spawnSync('where', [exe], { encoding: 'utf-8' })
  if (res.status !== 0) return []
  return (res.stdout || '').split('\n').map((l) => l.trim()).filter(Boolean)
}

// The compiler's own directories. `where` covers PATH and System32 — which is
// where the DLL happened to be on the machine this was first debugged on — but
// an LLVM or Visual-Studio-bundled clang keeps its runtime DLLs next to the
// compiler (`.../Llvm/x64/bin`) or one level over in `lib/`, and neither is
// necessarily on PATH in a CI shell.
let toolchainDirs = null
function clangDirs() {
  if (toolchainDirs) return toolchainDirs
  toolchainDirs = []
  for (const exe of ['clang.exe', 'clang++.exe', 'clang-cl.exe']) {
    for (const hit of whichAll(exe)) {
      const bin = path.dirname(hit)
      for (const dir of [bin, path.join(bin, '..', 'lib')]) {
        const resolved = path.resolve(dir)
        if (!toolchainDirs.includes(resolved) && fs.existsSync(resolved)) toolchainDirs.push(resolved)
      }
    }
  }
  return toolchainDirs
}

// Where a missing dependency might be found: caller-supplied directories first
// (the build's own staging output), then the standard search order, then the
// toolchain that produced the import in the first place.
function locate(name, extraDirs) {
  for (const dir of [...extraDirs, ...clangDirs()]) {
    const candidate = path.join(dir, name)
    if (fs.existsSync(candidate)) return candidate
  }
  const hit = whichAll(name)[0]
  return hit && fs.existsSync(hit) ? hit : null
}

/**
 * Copy every non-system DLL the staged libraries import into `dir`, following
 * the newly copied ones in turn.  Returns { vendored, missing } (both arrays of
 * names); `missing` is what could not be found on this machine, which is a
 * package that will not load anywhere its build machine's toolchain is absent.
 */
export function vendorWindowsDeps(dir, { log = () => {}, warn = () => {}, searchDirs = [] } = {}) {
  const present = new Map()  // lowercased name -> path, for the case-insensitive match
  for (const entry of fs.readdirSync(dir)) {
    if (entry.toLowerCase().endsWith('.dll')) present.set(entry.toLowerCase(), path.join(dir, entry))
  }

  const queue = [...present.values()]
  const vendored = []
  const missing = []
  const seen = new Set()

  while (queue.length) {
    const file = queue.shift()
    for (const name of peImports(file)) {
      const key = name.toLowerCase()
      if (isSystemDll(name) || present.has(key) || seen.has(key)) continue
      seen.add(key)
      const src = locate(name, searchDirs)
      if (!src) {
        missing.push(name)
        warn(`${path.basename(file)} imports ${name}, which is not on this machine; ` +
          `it cannot be vendored and the package will not load without it`)
        continue
      }
      const dst = path.join(dir, name)
      fs.copyFileSync(src, dst)
      present.set(key, dst)
      vendored.push(name)
      queue.push(dst)
      log(`vendored dependency ${name} (from ${src})`)
    }
  }
  if (!vendored.length && !missing.length) log('no extra Windows dependencies to vendor')
  return { vendored, missing }
}
