/* 设置中心（2026-11-03 票 3/4；2026-11-04 v2 供应商＋模型目录）的
   纯逻辑与表单渲染测试（不引 jsdom——与全站同口径）：
   - Headers 表单文本 K=V 解析（非法行保存前报错）；
   - 字体偏好：存储值归一 + localStorage 选择 → <html data-font>（document 桩）；
   - 供应商状态位（规则稿/模型模式）；
   - 供应商表单字段序照图二（renderToStaticMarkup 出静态结构验 label 顺序）、
     三协议选项、模型目录块。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  applyFontChoice, fontChoiceFromStorage, headersToText, parseHeadersText,
  FONT_CHOICES, FONT_KEY, ModelForm, providerModeOf,
} from './ModelPanel'
import type { ProviderDraft, ProviderRow } from '../api-models'

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
  const row = (over: Partial<ProviderRow> = {}): ProviderRow => ({
    id: 't1', label: 'T', base_url: 'https://x/v1', protocol: 'openai',
    key_hint: 'sk-…1234', note: '', builtin: false, ready: true,
    active: false, active_model: 'm', models: ['m'],
    ...over,
  })

  it('清单未到 / 空清单 / 全是没配齐的供应商 ＝ 规则稿模式', () => {
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

/* ---------------------------------------------------------------- 供应商表单（图二） */
const BLANK_DRAFT: ProviderDraft = {
  label: '', base_url: '', key: '', note: '', protocol: 'openai', models: [],
}

function renderForm(draft: ProviderDraft = BLANK_DRAFT, headersText = '',
                    defaultModels?: string[]): string {
  return renderToStaticMarkup(
    <ModelForm draft={draft} headersText={headersText} busy={false}
               defaultModels={defaultModels}
               onDraft={() => {}} onHeadersText={() => {}} onProbe={() => {}}
               onError={() => {}} onCancel={() => {}} onSubmit={() => {}} />)
}

describe('供应商表单字段序照图二：API 密钥 → 显示名称 → API 地址 → API 协议 → 思考深度 → 模型目录', () => {
  it('label 顺序逐字对上（Headers/备注殿后），模型目录是字段块', () => {
    const html = renderForm()
    const labels = [...html.matchAll(/<label[^>]*>([^<]{1,20})</g)].map((m) => m[1])
    expect(labels).toEqual(['API 密钥', '显示名称', 'API 地址', 'API 协议', '思考深度',
                             'Headers（可选）', '备注'])
    expect(html).toContain('模型目录')
  })

  it('API 协议三选（图三）：Chat Completions / Responses / Anthropic Messages', () => {
    const html = renderForm()
    expect(html).toContain('OpenAI Chat Completions')
    expect(html).toContain('OpenAI Responses')
    expect(html).toContain('Anthropic Messages')
  })

  it('模型目录：行式列表（型号名＋移除钮），空目录有一句空态', () => {
    const empty = renderForm()
    expect(empty).toContain('目录还空着')
    const filled = renderForm({ ...BLANK_DRAFT, models: ['A/B-1', 'C/D-2'] })
    expect(filled).toContain('A/B-1')
    expect(filled).toContain('C/D-2')
    expect(filled).toContain('从目录移除 A/B-1')
  })

  it('加型号走下拉直接选（rick 2026-11-04 裁决）：没有手动输入框', () => {
    const html = renderForm()
    expect(html).not.toContain('手动加')
    expect(html).not.toContain('加进目录')
  })

  it('「恢复默认模型」只在预置给了默认目录时出现；「获取可用模型」常在（都在目录标题行右侧）', () => {
    const html = renderForm()
    expect(html).toContain('获取可用模型')
    expect(html).not.toContain('恢复默认模型')
    const withDefault = renderForm(BLANK_DRAFT, '', ['a', 'b'])
    expect(withDefault).toContain('恢复默认模型')
    expect(withDefault.indexOf('恢复默认模型')).toBeLessThan(
      withDefault.indexOf('获取可用模型'))
  })

  it('key 输入留空＝沿用已存凭据（编辑态占位提示）', () => {
    const editing = renderForm({ ...BLANK_DRAFT, id: 't1', label: '旧名' })
    expect(editing).toContain('留空使用已保存凭据')
    expect(renderForm()).toContain('sk-…')
  })
})
