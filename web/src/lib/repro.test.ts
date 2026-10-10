/* 票 05（口径 A）· 出好了的三件套：从任务产物清单里**只认实产的三件**，
   按固定顺序（报告初稿 → 对勘本 → 红件清单）；缺谁不凑、杂项不进。
   （「对照差异报告」是回测件，常规跑不产出——不进这一排。） */
import { describe, expect, it } from 'vitest'
import { trioLinks } from './repro'

const art = (key: string, label: string, url: string) => ({
  key, label, name: `${key}.bin`, size: 1, url, primary: true,
})

describe('出好了 · 三件套（票 05 口径 A）', () => {
  it('只认三件并按固定顺序排', () => {
    const out = trioLinks([
      art('red_list', '红色件清单（Markdown）', '/u/red'),
      art('report', '报告初稿（Word）', '/u/rep'),
      art('collation', '对勘本（正文级对照）', '/u/col'),
    ])
    expect(out.map((x) => x.key)).toEqual(['report', 'collation', 'red_list'])
    expect(out[0].href).toBe('/u/rep')
    expect(out[0].label).toBe('报告初稿')
  })

  it('缺谁不凑：没有对勘本就只出两件', () => {
    const out = trioLinks([art('report', '报告初稿（Word）', '/u/rep')])
    expect(out.map((x) => x.key)).toEqual(['report'])
  })

  it('非三件套的产物（诊断报告/大表）不进这一排', () => {
    const out = trioLinks([
      art('diagnosis', '诊断报告（断言未过时的核对指引）', '/u/diag'),
      art('table2', '大表数据（CSV）', '/u/t2'),
      art('red_list', '红色件清单（Markdown）', '/u/red'),
    ])
    expect(out.map((x) => x.key)).toEqual(['red_list'])
  })

  it('空清单给空排（不编链接）', () => {
    expect(trioLinks([])).toEqual([])
  })
})
