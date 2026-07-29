// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-2.0-or-later

/*
 * record-release.mjs — record a package release in the joeedh/sculptblender-builds
 * repo.  The binaries themselves live as GitHub Release assets (so the repo
 * stays small and clonable); what lands in git is only:
 *
 *   releases/<tag>.json   a manifest: what was built, from what, with checksums
 *   RELEASES.md           a regenerated index of every manifest, newest first
 *
 * Run from .github/workflows/build-packages.yml's finalize job against a fresh
 * clone of the builds repo; it writes the files but never commits or pushes —
 * the workflow does that.
 *
 * Usage:
 *   node tools/record-release.mjs --repo DIR --tag TAG --sums DIR
 *                                 [--source-sha SHA] [--blender-branch B]
 *                                 [--config CFG] [--prerelease true|false]
 *   node tools/record-release.mjs --repo DIR --reindex
 *
 *   --repo DIR          Checkout of the builds repo to write into.
 *   --tag TAG           Release tag (also the release's asset prefix).
 *   --sums DIR          Directory of `<package>.sha256` files (sha256sum format:
 *                       "<hex>  <filename>"), one per platform.
 *   --source-sha SHA    sculptcore-blender-addon commit the packages were built from.
 *   --blender-branch B  Fork branch the Blender build came from.
 *   --config CFG        Engine build config the libs were compiled with.
 *   --prerelease B      Whether the release is marked as a pre-release.
 *   --reindex           Only regenerate RELEASES.md from the manifests already on
 *                       disk; record no new release. For repairing the index after
 *                       its format or ordering changes.
 */

import fs from 'node:fs'
import path from 'node:path'

const BUILDS_REPO = 'joeedh/sculptblender-builds'

// Asset-name suffix -> how the index describes the platform.  `asset` is the
// tag-free name the packaging workflow uploads under, which is what makes an
// always-latest URL addressable; releases predating that rename carry the tag
// in the name instead, hence the check in writeIndex().
const PLATFORMS = [
  { key: 'linux-x64', asset: 'sculptblender-linux-x64.tar.gz', label: 'Linux x64', note: '.tar.gz — extract and run ./blender' },
  { key: 'macos-arm64', asset: 'sculptblender-macos-arm64.tar.gz', label: 'macOS arm64', note: '.tar.gz — extract and run Blender.app' },
  { key: 'windows-x64', asset: 'sculptblender-windows-x64.zip', label: 'Windows x64', note: '.zip — extract and run blender.exe' },
]

function fail(msg) { console.error(`[record-release] error: ${msg}`); process.exit(1) }

function parseArgs(argv) {
  const opts = {
    repo: null, tag: null, sums: null, sourceSha: '', blenderBranch: '', config: '',
    prerelease: 'false', reindex: false,
  }
  for (let i = 0; i < argv.length; i++) {
    const next = () => argv[++i]
    switch (argv[i]) {
      case '--repo': opts.repo = path.resolve(next()); break
      case '--tag': opts.tag = next(); break
      case '--sums': opts.sums = path.resolve(next()); break
      case '--source-sha': opts.sourceSha = next(); break
      case '--blender-branch': opts.blenderBranch = next(); break
      case '--config': opts.config = next(); break
      case '--prerelease': opts.prerelease = next(); break
      case '--reindex': opts.reindex = true; break
      default: fail(`unknown option: ${argv[i]}`)
    }
  }
  if (!opts.repo) fail('--repo is required')
  if (!opts.reindex && (!opts.tag || !opts.sums)) fail('--tag and --sums are required (or pass --reindex)')
  return opts
}

// Read every *.sha256 in dir; sha256sum/shasum both write "<hex>  <name>".
function readChecksums(dir) {
  if (!fs.existsSync(dir)) fail(`checksum dir not found: ${dir}`)
  const assets = []
  for (const f of fs.readdirSync(dir).sort()) {
    if (!f.endsWith('.sha256')) continue
    const line = fs.readFileSync(path.join(dir, f), 'utf-8').trim().split('\n')[0]
    const m = /^([0-9a-fA-F]{64})\s+\*?(.+)$/.exec(line)
    if (!m) fail(`unparseable checksum file ${f}: ${line}`)
    const name = path.basename(m[2].trim())
    const plat = PLATFORMS.find((p) => name.includes(p.key))
    assets.push({ name, sha256: m[1].toLowerCase(), platform: plat ? plat.key : 'unknown' })
  }
  if (!assets.length) fail(`no .sha256 files in ${dir}`)
  // Index order, so the manifest and the tables read the same way everywhere.
  assets.sort((a, b) =>
    PLATFORMS.findIndex((p) => p.key === a.platform) - PLATFORMS.findIndex((p) => p.key === b.platform))
  return assets
}

function assetUrl(tag, name) {
  return `https://github.com/${BUILDS_REPO}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(name)}`
}

function releaseUrl(tag) {
  return `https://github.com/${BUILDS_REPO}/releases/tag/${encodeURIComponent(tag)}`
}

// GitHub's one stable-download mechanism: it redirects to the asset of that
// exact name on the newest published non-pre-release release.
function latestUrl(name) {
  return `https://github.com/${BUILDS_REPO}/releases/latest/download/${encodeURIComponent(name)}`
}

// What a manifest sorts by: its full `created_at` timestamp, falling back to the
// bare `date` for manifests written before that field existed. Ordering on the
// date alone put several builds of the same day in tag order, which is the sha
// suffix — alphabetical noise that buried the newest build under its siblings.
// A date-only key compares less than any timestamp of that day, so the older
// (untimestamped) manifests correctly sink below same-day timestamped ones.
function sortKey(m) { return m.created_at || m.date || '' }

// Rebuild RELEASES.md from every manifest on disk, newest first.
function writeIndex(repo) {
  const dir = path.join(repo, 'releases')
  const manifests = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf-8')))
    .sort((a, b) => {
      const ka = sortKey(a), kb = sortKey(b)
      if (ka !== kb) return ka < kb ? 1 : -1
      return a.tag < b.tag ? 1 : -1
    })

  const out = []
  out.push('# Releases')
  out.push('')
  out.push('Every SculptBlender package build, newest first. Binaries are GitHub')
  out.push('Release assets, not files in this repo — the links below download them')
  out.push('directly. Installation instructions live in [the README](./Readme.MD#installation).')
  out.push('')
  if (!manifests.length) {
    out.push('_No releases yet._')
  }

  // Both halves of the always-latest contract have to hold or the links 404:
  // the newest release GitHub calls "latest" must not be a pre-release, and it
  // must carry assets under the tag-free names. Only advertise the links when a
  // manifest on disk actually satisfies both — a dead download link on the
  // front page is worse than no link.
  const stable = manifests.find((m) => !m.prerelease
    && PLATFORMS.every((p) => (m.assets || []).some((a) => a.name === p.asset)))
  if (stable) {
    out.push('## Latest build')
    out.push('')
    out.push('These links always download the newest non-pre-release build — currently '
      + `[\`${stable.tag}\`](${releaseUrl(stable.tag)}). They are stable: bookmark or script them.`)
    out.push('')
    out.push('| platform | download |')
    out.push('| --- | --- |')
    for (const p of PLATFORMS) out.push(`| ${p.label} | [${p.asset}](${latestUrl(p.asset)}) |`)
    out.push('')
  }

  for (const m of manifests) {
    out.push(`## [${m.tag}](${releaseUrl(m.tag)})${m.prerelease ? ' — pre-release' : ''}`)
    out.push('')
    out.push(`Built ${m.date} from `
      + `[sculptcore-blender-addon@\`${(m.source_sha || '').slice(0, 7)}\`]`
      + `(https://github.com/joeedh/sculptcore-blender-addon/commit/${m.source_sha})`
      + `${m.blender_branch ? `, Blender fork branch \`${m.blender_branch}\`` : ''}`
      + `${m.config ? `, engine config \`${m.config}\`` : ''}.`)
    out.push('')
    out.push('| platform | download | sha256 |')
    out.push('| --- | --- | --- |')
    for (const a of m.assets) {
      const p = PLATFORMS.find((x) => x.key === a.platform)
      out.push(`| ${p ? p.label : a.platform} | [${a.name}](${assetUrl(m.tag, a.name)}) | \`${a.sha256}\` |`)
    }
    out.push('')
  }
  fs.writeFileSync(path.join(repo, 'RELEASES.md'), out.join('\n') + '\n')
}

function main() {
  const opts = parseArgs(process.argv.slice(2))
  if (!fs.existsSync(path.join(opts.repo, '.git'))) fail(`${opts.repo} is not a git checkout`)

  if (opts.reindex) {
    writeIndex(opts.repo)
    console.log('[record-release] regenerated RELEASES.md')
    return
  }

  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  const assets = readChecksums(opts.sums)
  const manifest = {
    tag: opts.tag,
    date: now.slice(0, 10),
    // Full timestamp: several builds a day is normal, and the index orders on this.
    created_at: now,
    prerelease: opts.prerelease === 'true',
    source_repo: 'joeedh/sculptcore-blender-addon',
    source_sha: opts.sourceSha,
    blender_branch: opts.blenderBranch,
    config: opts.config,
    release: releaseUrl(opts.tag),
    assets: assets.map((a) => ({ ...a, url: assetUrl(opts.tag, a.name) })),
  }

  const dir = path.join(opts.repo, 'releases')
  fs.mkdirSync(dir, { recursive: true })
  // Tags are filename-safe by construction (build-<date>-<sha>), but a
  // hand-passed --tag could contain a slash; keep it inside releases/.
  const file = path.join(dir, `${opts.tag.replace(/[/\\]/g, '-')}.json`)
  fs.writeFileSync(file, JSON.stringify(manifest, null, 2) + '\n')
  console.log(`[record-release] wrote ${path.relative(opts.repo, file)}`)

  writeIndex(opts.repo)
  console.log('[record-release] regenerated RELEASES.md')
}

main()
