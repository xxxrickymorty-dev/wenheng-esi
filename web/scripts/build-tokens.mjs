#!/usr/bin/env node
/* 令牌生成器：把 web/design/tokens/core.json 摊成 web/src/tokens.css。
   零依赖、离线可跑——不装 style-dictionary，不引第二个构建依赖。
   将来真要跨端（小程序 / 移动端 / 设计工具）再换 style-dictionary，
   这个脚本就是它的最小替身：core.json 是唯一真相，tokens.css 由它投影出来。
   用法：npm run tokens（build 会自动先跑一次）。 */

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '../design/tokens/core.json')
const OUT = resolve(HERE, '../src/tokens.css')

/* 出的顺序固定，方便 diff；core.json 里多出来的段按文件顺序接在后面 */
const ORDER = ['color', 'font', 'radius', 'shadow', 'type']
const LABEL = { color: '颜色', font: '字体', radius: '圆角', shadow: '阴影', type: '字号' }

const raw = JSON.parse(readFileSync(SRC, 'utf8'))
const sections = ORDER.filter((k) => k in raw)
  .concat(Object.keys(raw).filter((k) => !k.startsWith('$') && !ORDER.includes(k)))

const lines = []
let count = 0
for (const section of sections) {
  const group = raw[section]
  const entries = Object.entries(group).filter(([k]) => !k.startsWith('$'))
  if (entries.length === 0) continue
  lines.push(`  /* ${LABEL[section] ?? section} */`)
  for (const [key, value] of entries) {
    if (typeof value !== 'string' || value === '') {
      throw new Error(`令牌 ${section}.${key} 的值必须是字符串，现在是 ${JSON.stringify(value)}`)
    }
    lines.push(`  --${key}:${value};`)
    count += 1
  }
}

const css = [
  '/* 自动生成，不要手改。改令牌请改 web/design/tokens/core.json 再跑 npm run tokens */',
  '/* 生成器：web/scripts/build-tokens.mjs（零依赖；将来跨端再换 style-dictionary） */',
  '/* 陈列馆木色（--lib-*）不参与主题，仍写在 web/src/index.css */',
  ':root{',
  ...lines,
  '}',
  '',
].join('\n')

writeFileSync(OUT, css, 'utf8')
console.log(`已生成 ${OUT}：${sections.length} 段、${count} 个令牌`)
