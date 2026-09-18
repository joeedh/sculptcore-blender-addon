// SPDX-FileCopyrightText: 2026 Blender Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// Apply tools/genTS.ts's header/formatter to declarations generated from the native DLL.
import fs from 'node:fs'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
import {getNativeEOL, toEOL} from '../../engine/tools/eol.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(path.join(root, 'engine/package.json'))
const prettier = require('@pathtx/prettier')
const output = path.resolve(root, 'claudeMemory/tests', process.argv[2])
const reportPath = path.join(output, 'results.json')
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
const baseDir = path.join(root, 'engine/typescript')
const config = (await prettier.resolveConfig(baseDir)) ?? {}
const eol = getNativeEOL(baseDir)
const header = "/* Warning: auto-generated file! Regenerate with 'pnpm build' in 'tools/' folder. */\n"
report.formatted_typescript = {}
for (const name of Object.keys(report.artifacts).filter(name => name.startsWith('typescript/'))) {
  const relative = name.slice('typescript/'.length)
  const target = path.resolve(baseDir, relative)
  if (path.relative(baseDir, target).startsWith('..')) throw Error('Generated path outside destination')
  const raw = header + fs.readFileSync(path.join(output, name), 'utf8')
  const formatted = toEOL(await prettier.format(raw, {
    ...config, parser: 'typescript', filepath: target, endOfLine: eol === '\r\n' ? 'crlf' : 'lf',
  }), eol)
  fs.writeFileSync(target, formatted)
  report.formatted_typescript[relative] = createHash('sha256').update(formatted).digest('hex')
}
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n')
console.log(`Formatted ${Object.keys(report.formatted_typescript).length} generated TypeScript files`)
