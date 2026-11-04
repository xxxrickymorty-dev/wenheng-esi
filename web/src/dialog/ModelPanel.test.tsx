/* 设置中心（2026-11-03 票 3/4）的纯逻辑与表单渲染测试（不引 jsdom——与全站同口径）：
   - Headers 表单文本 K=V 解析（非法行保存前报错）；
   - 字体偏好：存储值归一 + localStorage 选择 → <html data-font>（document 桩）；
   - 供应商表单字段序照图五（renderToStaticMarkup 出静态结构验 label 顺序）。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  applyFontChoice, fontChoiceFromStorage, headersToText, parseHeadersText,
  FONT_CHOICES, FONT_KEY, ModelForm, providerModeOf,
} from './ModelPanel'
import type { ModelDraft, ModelRow } from '../api-models'

/* ---------------------------------------------------------------- Headers K=V（票 4） */
describe('Headers 表单文本解析：每行 K=V，空行忽略，非法行报错', () => {
  it('合法行成对收进对象', () => {
    const { headers, error } = parseHeadersText('X-Org=ynu\nX-Trace-Id = abc-123\n')
    expect(error).toBe('')
    expect(headers).toEqual({ 'X-Org': 'ynu', 'X-Trace-Id': 'abc-123' })
  })

  it('空行与纯空白行忽略', () => {
    const { headers, error } = parseHeadersText('\nX-Org=ynu\n   \n')
    expect(error).toBe('')
    expect(headers).toEqual({ 'X-Org': 'ynu' })
  })

  it('缺等号 / 缺值 / 缺名字 → 整份拒绝并给那行原文', () => {
    expect(parseHeadersText('X-Org').error).toContain('X-Org')
    expect(parseHeadersText('X-Org=').error).toContain('X-Org')
    expect(parseHeadersText('=ynu').error).not.toBe('')
    expect(parseHeadersText('X-Org=ynu\n坏行').error).toContain('坏行')
  })

  it('头名字带字母数字连字符以外的字符 → 拒收', () => {
    expect(parseHeadersText('X_Org=ynu').error).toContain('X_Org')
    expect(parseHeadersText('坏 头=ynu').error).not.toBe('')
    expect(parseHeadersText('X-Org=ynu').error).toBe('')
  })

  it('headersToText 与 parseHeadersText 互逆（「改」时预填用）', () => {
    const stored = { 'X-Org': 'ynu', 'X-Trace-Id': 'abc-123' }
    const { headers, error } = parseHeadersText(headersToText(stored))
    expect(error).toBe('')
    expect(headers).toEqual(stored)
    expect(headersToText(undefined)).toBe('')
  })
})

/* ---------------------------------------------------------------- 字体偏好（票 3） */
describe('正文字体三选：存储值归一 + localStorage → <html data-font>', () => {
  const store = new Map<string, string>()
  const dataset: Record<string, string> = {}

  afterEach(() => {
    store.clear()
    delete dataset.font
    vi.unstubAllGlobals()
  })

  function stubDom() {
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v) },
    })
    vi.stubGlobal('document', { documentElement: { dataset } })
  }

  it('读不到 / 不认得 → 衬线（缺省）', () => {
    expect(fontChoiceFromStorage(null)).toBe('serif')
    expect(fontChoiceFromStorage('')).toBe('serif')
    expect(fontChoiceFromStorage('weird')).toBe('serif')
  })

  it('三张卡＝衬线/非衬线/楷体，衬线在前（缺省）', () => {
    expect(FONT_CHOICES.map((c) => c.value)).toEqual(['serif', 'sans', 'kai'])
    expect(FONT_CHOICES.map((c) => c.label)).toEqual(['衬线', '非衬线', '楷体'])
  })

  it('选非衬线/楷体：挂 <html data-font>，刷新后从 localStorage 归一回来仍一致', () => {
    stubDom()
    // 界面节选「楷体」：立即生效 + 存进 localStorage（pickFont 的两步，这里验效果两端）
    applyFontChoice('kai')
    store.set(FONT_KEY, 'kai')
    expect(dataset.font).toBe('kai')
    expect(fontChoiceFromStorage(store.get(FONT_KEY) ?? null)).toBe('kai')

    applyFontChoice('sans')
    store.set(FONT_KEY, 'sans')
    expect(dataset.font).toBe('sans')
    expect(fontChoiceFromStorage(store.get(FONT_KEY) ?? null)).toBe('sans')
  })

  it('选衬线＝回缺省：删掉 data-font 属性', () => {
    stubDom()
    document.documentElement.dataset.font = 'kai'
    applyFontChoice('serif')
    expect('font' in dataset).toBe(false)
  })
})

/* ---------------------------------------------------------------- 供应商状态显性（2026-11-04） */
describe('供应商状态显性：未配置＝规则稿模式，已配置＝模型模式', () => {
  const row = (over: Partial<ModelRow> = {}): ModelRow => ({
    id: 't1', label: 'T', base_url: 'https://x/v1', model: 'm',
    key_hint: 'sk-…1234', note: '', builtin: false, ready: true, active: false,
    ...over,
  })

  it('清单未到 / 空清单 / 全是没配齐的条目 ＝ 规则稿模式', () => {
    expect(providerModeOf(undefined)).toBe('规则稿模式')
    expect(providerModeOf([])).toBe('规则稿模式')
    expect(providerModeOf([row({ ready: false })])).toBe('规则稿模式')
  })

  it('有一条配齐的（含 .env 部署配置行）＝ 模型模式', () => {
    expect(providerModeOf([row({ ready: false }), row({ id: '', builtin: true })]))
      .toBe('模型模式')
    expect(providerModeOf([row()])).toBe('模型模式')
  })
})

/* ---------------------------------------------------------------- 供应商表单（票 3 图五） */
const BLANK_DRAFT: ModelDraft = { label: '', base_url: '', model: '', key: '', note: '', protocol: 'openai' }

function renderForm(draft: ModelDraft = BLANK_DRAFT, headersText = ''): string {
  return renderToStaticMarkup(
    <ModelForm draft={draft} headersText={headersText} busy={false}
               onDraft={() => {}} onHeadersText={() => {}}
               onProbe={() => {}} onCancel={() => {}} onSubmit={() => {}} />)
}

describe('供应商表单字段序照图五：名称 → Base URL → API Key → 模型 → Headers → API 协议', () => {
  it('label 顺序逐字对上（备注殿后收尾）', () => {
    const html = renderForm()
    const labels = [...html.matchAll(/<label[^>]*>([^<]{1,20})</g)].map((m) => m[1])
    expect(labels).toEqual(['名称', 'Base URL', 'API Key', '模型', 'Headers（可选）', 'API 协议', '备注'])
  })

  it('Headers 是多行文本框；API 协议单选 OpenAI Compatible；key 输入留空＝不改', () => {
    const html = renderForm(BLANK_DRAFT, 'X-Org=ynu')
    expect(html).toContain('<textarea')
    expect(html).toContain('X-Org=ynu')
    expect(html).toContain('OpenAI Compatible')
    expect(html).toContain('type="password"')
    /* 「留空＝不改原来那把」是编辑态（draft.id 在）的占位提示 */
    const editing = renderForm({ ...BLANK_DRAFT, id: 't1', label: '旧名' })
    expect(editing).toContain('留空＝不改原来那把')
  })
})
