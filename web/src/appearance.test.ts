/* 报告外观四轴（src/appearance.ts）的纯逻辑测试（不引 jsdom——与全站同口径）：
   - 旧值归一（字体 serif/sans、皮肤/模板不认得回落缺省）；
   - 四轴读写；系统皮肤轨与报告皮肤轨是两个独立键，互不串；
   - 生成请求体带 template / skin_rpt / font 三字段，绝不带 skin_sys。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_FONT, DEFAULT_SKIN, DEFAULT_TEMPLATE,
  FONT_KEY, SKIN_RPT_KEY, SKIN_SYS_KEY, TEMPLATE_KEY,
  normalizeFont, normalizeSkin, normalizeTemplate,
  readAppearanceForRequest, readFont, readSkinRpt, readSkinSys, readTemplate,
  writeFont, writeSkinRpt, writeSkinSys, writeTemplate,
} from './appearance'
import { buildCompareJobBody, buildReportJobBody } from './api-monitor'

const store = new Map<string, string>()
afterEach(() => {
  store.clear()
  vi.unstubAllGlobals()
})
function stubLs() {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  })
}

describe('四轴归一', () => {
  it('字体：老值 serif→song、sans→hei、kai→kai；其余回落会泽宋', () => {
    expect(normalizeFont(null)).toBe('song')
    expect(normalizeFont('weird')).toBe('song')
    expect(normalizeFont('serif')).toBe('song')
    expect(normalizeFont('sans')).toBe('hei')
    expect(normalizeFont('kai')).toBe('kai')
    expect(normalizeFont('xing')).toBe('xing')
  })
  it('皮肤：不认得回落会泽绿；夜泊认得', () => {
    expect(normalizeSkin(null)).toBe('huize')
    expect(normalizeSkin('nope')).toBe('huize')
    expect(normalizeSkin('yebo')).toBe('yebo')
  })
  it('模板：不认得回落 A；C 认得', () => {
    expect(normalizeTemplate(null)).toBe('A')
    expect(normalizeTemplate('Z')).toBe('A')
    expect(normalizeTemplate('C')).toBe('C')
  })
})

describe('四轴读写与本机缺省', () => {
  it('模板缺省 A，写入后读回一致', () => {
    stubLs()
    expect(readTemplate()).toBe(DEFAULT_TEMPLATE)
    writeTemplate('D'); expect(readTemplate()).toBe('D')
    expect(store.get(TEMPLATE_KEY)).toBe('D')
  })
  it('字体缺省会泽宋，写入后读回一致', () => {
    stubLs()
    expect(readFont()).toBe(DEFAULT_FONT)
    writeFont('fang'); expect(readFont()).toBe('fang')
    expect(store.get(FONT_KEY)).toBe('fang')
  })
})

describe('系统皮肤轨与报告皮肤轨各自独立、互不串', () => {
  it('两键分开存、分开读；改系统轨不影响报告轨', () => {
    stubLs()
    writeSkinSys('zhusha')
    writeSkinRpt('yebo')
    expect(readSkinSys()).toBe('zhusha')
    expect(readSkinRpt()).toBe('yebo')
    // 改系统轨，报告轨不变
    writeSkinSys('qingshan')
    expect(readSkinSys()).toBe('qingshan')
    expect(readSkinRpt()).toBe('yebo')
    // 改报告轨，系统轨不变
    writeSkinRpt('tenghuang')
    expect(readSkinRpt()).toBe('tenghuang')
    expect(readSkinSys()).toBe('qingshan')
  })
  it('两键确为不同存储键', () => {
    expect(SKIN_SYS_KEY).toBe('wenheng.ui.skin.sys')
    expect(SKIN_RPT_KEY).toBe('wenheng.ui.skin.rpt')
    expect(SKIN_SYS_KEY).not.toBe(SKIN_RPT_KEY)
  })
})

describe('生成请求体：带三字段、不带 skin_sys', () => {
  it('readAppearanceForRequest 返回 template / skin_rpt / font，无 skin_sys', () => {
    stubLs()
    writeTemplate('B'); writeSkinRpt('zhusha'); writeFont('hei')
    const r = readAppearanceForRequest()
    expect(r).toEqual({ template: 'B', skin_rpt: 'zhusha', font: 'hei' })
    expect('skin_sys' in r).toBe(false)
  })
  it('单校任务体：school + force + 三字段，无 skin_sys', () => {
    stubLs()
    const body = buildReportJobBody('清华大学', true)
    expect(body.school).toBe('清华大学')
    expect(body.force).toBe(true)
    expect(body.template).toBe(DEFAULT_TEMPLATE)
    expect(body.skin_rpt).toBe(DEFAULT_SKIN)
    expect(body.font).toBe(DEFAULT_FONT)
    expect('skin_sys' in body).toBe(false)
  })
  it('对比任务体：schools + 三字段，无 skin_sys', () => {
    stubLs()
    const body = buildCompareJobBody(['清华大学', '北京大学'])
    expect(body.schools).toEqual(['清华大学', '北京大学'])
    expect(body.template).toBe(DEFAULT_TEMPLATE)
    expect(body.skin_rpt).toBe(DEFAULT_SKIN)
    expect(body.font).toBe(DEFAULT_FONT)
    expect('skin_sys' in body).toBe(false)
  })
})
