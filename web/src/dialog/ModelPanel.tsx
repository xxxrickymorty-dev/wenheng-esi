/* 模型面板（2026-10-29；2026-11-03 设置中心双节 hub；2026-11-04 v2
   供应商＋模型目录，照 DSH 图二形制）：
   两件事分开——切当前模型（输入框左下「模型」菜单，谁都能点，写口在后端）、
   配置与偏好（设置弹窗，左栏两节：供应商＝管理员配网关与模型目录；界面＝正文字体）。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Me } from '../api'
import {
  getModels, listRemoteModels, removeProvider, saveProvider, setActiveModel,
  testModel, PROTOCOL_LABELS,
  type ModelsPayload, type ProviderDraft, type ProviderRow, type Protocol,
  type RemoteModels,
} from '../api-models'
import {
  TEMPLATES, SKINS, SKIN_GROUPS, FONTS,
  readTemplate, writeTemplate,
  readSkinSys, writeSkinSys, applySystemSkin,
  readSkinRpt, writeSkinRpt,
  readFont, writeFont, applyFontChoice,
  readAppearance,
  type TemplateId, type SkinId, type FontId,
} from '../appearance'
import { ConfirmButton } from '../ConfirmButton'
import { errorNote } from '../lib/status'
import { Icon } from '../icons'
import { CallStatsBlock } from './CallStats'

const EMPTY_DRAFT: ProviderDraft = {
  label: '', base_url: '', key: '', note: '', protocol: 'openai', models: [], params: {},
}

/* ── 思考深度（2026-11-05）：推理型型号的输出预算花在「想」上还是「写」上 ──
   空串＝不带这个参数（网关缺省）；GLM-5.3-Flash 缺省档实测把 8192 tokens 全花在
   思考上、正文 0 字（50–90 秒），低档 1.7 秒出正文——报告生成能不能跑通就靠这一档。 */
export const EFFORT_CHOICES: { value: string; label: string }[] = [
  { value: '', label: '网关缺省' },
  { value: 'low', label: '低（思考型型号建议）' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]

/* ── 界面节·字体与外观轴：选项表、存储读写、挂 <html> 副作用都来自 src/appearance.ts
   （四轴唯一真相）。旧接口名 FONT_KEY / fontChoiceFromStorage / applyFontChoice /
   FONT_CHOICES 仍从这里再导出，测试照旧 import。 ── */
export {
  FONT_KEY, FONT_CHOICES, fontChoiceFromStorage, applyFontChoice,
} from '../appearance'

/* 模板缩略图（五套骨架，各画各的版式；色是固定示意，不随皮肤变） */
function TemplateThumb({ id }: { id: TemplateId }) {
  const common = { fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  switch (id) {
    case 'A': return (
      <svg viewBox="0 0 72 50" stroke="#3D4A45" strokeWidth={1.7} {...common}>
        <rect x="2" y="3" width="68" height="44" fill="#FFFDF7" stroke="#C7C0AF" />
        <line x1="19" y1="3" x2="19" y2="47" stroke="#B08E48" />
        <line x1="10" y1="9" x2="10" y2="22" strokeWidth={2.6} />
        <line x1="10" y1="26" x2="10" y2="33" />
        <line x1="25" y1="10" x2="62" y2="10" strokeWidth={2.6} />
        <line x1="25" y1="15" x2="47" y2="15" stroke="#BAB3A3" />
        <line x1="25" y1="19" x2="52" y2="19" stroke="#BAB3A3" />
        <line x1="25" y1="26" x2="66" y2="26" stroke="#BAB3A3" />
        <line x1="25" y1="31" x2="66" y2="31" stroke="#BAB3A3" />
        <line x1="25" y1="36" x2="66" y2="36" stroke="#BAB3A3" />
        <line x1="25" y1="41" x2="66" y2="41" stroke="#BAB3A3" />
      </svg>)
    case 'B': return (
      <svg viewBox="0 0 72 50" stroke="#3D4A45" strokeWidth={1.7} {...common}>
        <rect x="2" y="3" width="68" height="44" fill="#FFFDF7" stroke="#C7C0AF" />
        <line x1="7" y1="8" x2="30" y2="8" stroke="#BAB3A3" />
        <line x1="59" y1="8" x2="66" y2="8" stroke="#BAB3A3" />
        <line x1="7" y1="15" x2="52" y2="15" strokeWidth={2.8} />
        <line x1="7" y1="19" x2="44" y2="19" stroke="#BAB3A3" />
        <line x1="7" y1="22" x2="38" y2="22" stroke="#BAB3A3" />
        <rect x="6" y="26" width="14.5" height="8" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="22.5" y="26" width="14.5" height="8" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="39" y="26" width="14.5" height="8" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="55.5" y="26" width="14.5" height="8" fill="#F0EDE2" stroke="#B6AD98" />
        <line x1="6" y1="38" x2="66" y2="38" stroke="#3D4A45" />
        <line x1="6" y1="41.5" x2="66" y2="41.5" stroke="#BAB3A3" />
        <line x1="6" y1="45" x2="66" y2="45" stroke="#BAB3A3" />
      </svg>)
    case 'C': return (
      <svg viewBox="0 0 72 50" stroke="#3D4A45" strokeWidth={1.7} {...common}>
        <rect x="6" y="4" width="60" height="13" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="10" y="20" width="56" height="13" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="6" y="36" width="60" height="11" fill="#F0EDE2" stroke="#B6AD98" />
        <rect x="58" y="6" width="6" height="6" fill="#B08E48" stroke="none" />
        <rect x="58" y="22" width="6" height="6" fill="#B08E48" stroke="none" />
        <rect x="58" y="38" width="6" height="6" fill="#B08E48" stroke="none" />
        <line x1="10" y1="10" x2="40" y2="10" stroke="#BAB3A3" />
        <line x1="14" y1="26" x2="44" y2="26" stroke="#BAB3A3" />
        <line x1="10" y1="42" x2="40" y2="42" stroke="#BAB3A3" />
      </svg>)
    case 'D': return (
      <svg viewBox="0 0 72 50" stroke="#C9A961" strokeWidth={1.7} {...common}>
        <rect x="2" y="3" width="68" height="44" fill="#1D252B" stroke="#1D252B" />
        <line x1="8" y1="12" x2="64" y2="12" />
        <line x1="8" y1="15" x2="64" y2="15" />
        <line x1="14" y1="23" x2="58" y2="23" stroke="#D6D0C2" strokeWidth={2.6} />
        <line x1="8" y1="31" x2="64" y2="31" stroke="#D6D0C2" />
        <line x1="8" y1="36" x2="64" y2="36" stroke="#D6D0C2" />
        <line x1="8" y1="41" x2="50" y2="41" stroke="#D6D0C2" />
      </svg>)
    case 'E': return (
      <svg viewBox="0 0 72 50" stroke="#3D4A45" strokeWidth={1.7} {...common}>
        <rect x="2" y="3" width="68" height="44" fill="#FFFDF7" stroke="#C7C0AF" />
        <rect x="2" y="3" width="68" height="7" fill="#DDE6E2" stroke="#9BA8A1" />
        <line x1="7" y1="6.5" x2="30" y2="6.5" stroke="#5C6D65" />
        <line x1="35" y1="14" x2="35" y2="45" />
        <line x1="53" y1="14" x2="53" y2="45" stroke="#B08E48" />
        <line x1="6" y1="16" x2="31" y2="16" stroke="#BAB3A3" />
        <line x1="6" y1="21" x2="31" y2="21" stroke="#BAB3A3" />
        <line x1="6" y1="26" x2="31" y2="26" stroke="#BAB3A3" />
        <line x1="6" y1="31" x2="31" y2="31" stroke="#BAB3A3" />
        <line x1="6" y1="36" x2="31" y2="36" stroke="#BAB3A3" />
        <line x1="6" y1="41" x2="31" y2="41" stroke="#BAB3A3" />
        <line x1="38" y1="16" x2="50" y2="16" stroke="#BAB3A3" />
        <line x1="38" y1="21" x2="50" y2="21" stroke="#BAB3A3" />
        <line x1="38" y1="26" x2="50" y2="26" stroke="#BAB3A3" />
        <line x1="56" y1="16" x2="66" y2="16" stroke="#BAB3A3" />
        <line x1="56" y1="20" x2="66" y2="20" stroke="#BAB3A3" />
        <line x1="56" y1="24" x2="66" y2="24" stroke="#BAB3A3" />
      </svg>)
  }
}

/* 选中勾：复用语站统一的 icons.tsx（24 视框 / 1.7 描边 / 圆头）。 */
function Tick() {
  return <Icon name="check" size={14} className="ap-tick" />
}

/* ── 供应商节·Headers 表单（票 4）：textarea 每行 `K=V`，空行忽略，非法行保存前报错 ── */
/** 表单文本 → headers 对象；不合法整份拒绝（返回 error），不猜不静默清洗。 */
export function parseHeadersText(text: string): { headers: Record<string, string>; error: string } {
  const headers: Record<string, string> = {}
  for (const rawLine of String(text || '').split('\n')) {
    const line = rawLine.trim()
    if (!line) continue                                   // 空行忽略
    const eq = line.indexOf('=')
    const key = (eq < 0 ? '' : line.slice(0, eq)).trim()
    const value = (eq < 0 ? '' : line.slice(eq + 1)).trim()
    if (!key || !value) return { headers: {}, error: `这一行不是「名字=值」的写法：${line}` }
    if (!/^[A-Za-z0-9-]+$/.test(key)) {
      return { headers: {}, error: `头名字只能用字母、数字和连字符：${key}` }
    }
    headers[key] = value
  }
  return { headers, error: '' }
}
/** 已存 headers 对象 → 表单文本（K=V 每行一条，「改」时预填用）。 */
export function headersToText(headers: Record<string, string> | undefined): string {
  return Object.entries(headers ?? {}).map(([k, v]) => `${k}=${v}`).join('\n')
}

/* ── 供应商状态显性（2026-11-04 rick 定）：一枚状态位，两态——
   供应商未配置＝「规则稿模式」（全系统三产线＋问文衡直接规则稿）；已配置＝「模型模式」。
   判据＝清单里存在配齐的供应商（地址/key/模型目录全；含 `.env` 部署配置行）——
   只读 `/api/models` 现有字段，不新造口径、不猜字段；供应商开启后强制不回落
   的语义由后端改，界面只如实展示。规则稿模式表单照常可填（保存即「添加供应商」）。 */
export function providerModeOf(providers: ProviderRow[] | undefined): '模型模式' | '规则稿模式' {
  return (providers ?? []).some((p) => p.ready) ? '模型模式' : '规则稿模式'
}

/** 输入框左下那颗按钮 ＋ 向上弹出的清单：每个配齐供应商的目录型号平铺一列。 */
export function ModelMenu({ payload, busy, onPicked }: {
  payload: ModelsPayload | null
  busy: boolean
  onPicked: (provider: string, model: string) => void
}) {
  const [open, setOpen] = useState(false)
  const active = payload?.active ?? { provider: '', model: '' }
  const currentProvider = (payload?.providers ?? []).find(
    (p) => p.active && (!active.model || p.models.includes(active.model)))
  const current = active.model || currentProvider?.active_model
    || currentProvider?.label || '未配置模型'

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [open])

  return (
    <div className="mdl-menu-wrap" onClick={(e) => e.stopPropagation()}>
      <button type="button" className="mdl-menu-btn" disabled={busy}
              aria-haspopup="menu" aria-expanded={open}
              title="换一个模型来回答"
              onClick={() => setOpen((v) => !v)}>
        <span className="mdl-menu-dot" data-ready={currentProvider?.ready ? '1' : '0'} aria-hidden="true" />
        {current}
        <span className="mdl-caret" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="mdl-menu" role="menu">
          {(payload?.providers ?? []).filter((p) => p.ready && p.models.length).flatMap((p) =>
            p.models.map((m) => {
              const on = p.active && active.model === m
              return (
                <button key={`${p.id}:${m}`} type="button" role="menuitemradio"
                        aria-checked={on}
                        className={`mdl-menu-item${on ? ' on' : ''}`}
                        title={`${p.label} · ${p.base_url}`}
                        onClick={() => { setOpen(false); if (!on) onPicked(p.id, m) }}>
                  <span className="mdl-menu-k">{m}</span>
                  <span className="mdl-menu-v">{p.label}</span>
                  {on && <span className="mdl-menu-tick" aria-hidden="true">✓</span>}
                </button>
              )
            }))}
          {!payload && <p className="mdl-menu-cap">正在读模型清单…</p>}
        </div>
      )}
    </div>
  )
}

/** 新增/编辑供应商表单（图二字段序）：API 密钥（留空使用已保存凭据）/
    显示名称 / API 地址 / API 协议（三选）/ 模型目录（挑过的型号子集：
    获取可用模型点选加入、可手动加、恢复默认）/ Headers（可选，多行 K=V）/ 备注。 */
export function ModelForm({ draft, headersText, busy, defaultModels, onDraft,
                            onHeadersText, onProbe, onCancel, onSubmit, onError }: {
  draft: ProviderDraft
  headersText: string
  busy: boolean
  /** 预置目录（地址匹配上预置时给）：「恢复默认模型」用 */
  defaultModels?: string[]
  onDraft: (d: ProviderDraft) => void
  onHeadersText: (t: string) => void
  onProbe: () => void
  onCancel: () => void
  onSubmit: () => void
  onError: (msg: string) => void
}) {
  const [remote, setRemote] = useState<RemoteModels | null>(null)
  const [fetching, setFetching] = useState(false)
  const inCatalog = useMemo(() => new Set(draft.models ?? []), [draft.models])

  function addModel(m: string) {
    const model = m.trim()
    if (!model || inCatalog.has(model)) return
    onDraft({ ...draft, models: [...(draft.models ?? []), model] })
  }
  function removeModel(m: string) {
    onDraft({ ...draft, models: (draft.models ?? []).filter((x) => x !== m) })
  }

  async function fetchRemote() {
    setFetching(true); onError(''); setRemote(null)
    try {
      const { headers, error } = parseHeadersText(headersText)
      if (error) { onError(error); return }
      const r = draft.id
        ? await listRemoteModels({ id: draft.id, headers: headers || undefined })
        : await listRemoteModels({ base_url: draft.base_url, key: draft.key,
                                   headers: headers || undefined })
      setRemote(r)
      if (!r.ok) onError(r.msg)
    } catch (e) {
      onError(errorNote(e, '拉型号清单',
        { n404: '演示服务还没更新到这一版——重启服务后再点一次。' }))
    } finally {
      setFetching(false)
    }
  }

  const remoteLeft = (remote?.ids ?? []).filter((m) => !inCatalog.has(m))

  return (
    <form className="mdl-form" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <p className="mdl-hint">{draft.id ? `修改「${draft.label}」` : '新增一条供应商'}</p>
      <label>API 密钥<input value={draft.key} type="password" autoComplete="off"
              placeholder={draft.id ? '留空使用已保存凭据' : 'sk-…'}
              onChange={(e) => onDraft({ ...draft, key: e.target.value })} /></label>
      <label>显示名称<input value={draft.label} placeholder="例如 云南大学网关（new-api）"
              onChange={(e) => onDraft({ ...draft, label: e.target.value })} /></label>
      <label>API 地址<input value={draft.base_url} placeholder="服务商给的接口地址，一般以 v1 结尾"
              onChange={(e) => onDraft({ ...draft, base_url: e.target.value })} /></label>
      <label>API 协议<select value={draft.protocol ?? 'openai'}
              onChange={(e) => onDraft({ ...draft, protocol: e.target.value as Protocol })}>
        {(Object.entries(PROTOCOL_LABELS) as [Protocol, string][]).map(([v, name]) => (
          <option key={v} value={v}>{name}</option>
        ))}
      </select></label>
      <label title="思考型型号（如 GLM-5.3-Flash）把档位调低才写得出正文；普通型号保持缺省">
        思考深度<select value={draft.params?.reasoning_effort ?? ''}
              onChange={(e) => onDraft({ ...draft, params: { ...(draft.params ?? {}),
                                                             reasoning_effort: e.target.value } })}>
        {EFFORT_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select></label>
      <div className="mdl-field">
        <div className="mdl-cat-head">
          <span className="mdl-field-k">模型目录</span>
          <span className="mdl-cat-links">
            {defaultModels && defaultModels.length > 0 && (
              <button type="button" className="mdl-cat-link" disabled={busy}
                      title={`恢复成预置的 ${defaultModels.length} 个型号`}
                      onClick={() => { setRemote(null); onDraft({ ...draft, models: [...defaultModels] }) }}>
                恢复默认模型
              </button>
            )}
            <button type="button" className="mdl-cat-link" disabled={busy || fetching}
                    title="从这条网关拉型号清单，下拉直接选"
                    onClick={() => void fetchRemote()}>
              {fetching ? '拉取中…' : '获取可用模型'}
            </button>
          </span>
        </div>
        <div className="mdl-cat">
          {(draft.models ?? []).map((m) => (
            <div key={m} className="mdl-cat-row">
              <code title={m}>{m}</code>
              <button type="button" className="mdl-cat-x" aria-label={`从目录移除 ${m}`}
                      title={`从目录移除 ${m}`}
                      onClick={() => removeModel(m)}>✕</button>
            </div>
          ))}
          {!(draft.models ?? []).length && (
            <p className="mdl-cat-empty">目录还空着——「获取可用模型」后下拉直接选</p>
          )}
        </div>
        {remoteLeft.length > 0 && (
          <select className="mdl-cat-pick" value="" aria-label="选一个可用型号加进目录"
                  onChange={(e) => addModel(e.target.value)}>
            <option value="">从 {remoteLeft.length} 个可用型号里选…</option>
            {remoteLeft.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        )}
      </div>
      <label>Headers（可选）<textarea rows={3} value={headersText}
              placeholder={'每行一条：名字=值（空行忽略）\n例如 X-Org=ynu'}
              onChange={(e) => onHeadersText(e.target.value)} /></label>
      <label>备注<input value={draft.note ?? ''} placeholder="给馆员看的一句话"
              onChange={(e) => onDraft({ ...draft, note: e.target.value })} /></label>
      <div className="mdl-form-acts">
        <button type="submit" className="mdl-act primary" disabled={busy}>保存</button>
        <button type="button" className="mdl-act ghost" disabled={busy} onClick={onProbe}>
          先测一下
        </button>
        <button type="button" className="mdl-act ghost" onClick={onCancel}>取消</button>
      </div>
    </form>
  )
}

/** 设置弹窗（票 3 双节 hub）：左栏导航（供应商/界面），默认落供应商。
    39 分册 I：焦点圈禁。弹层挂在 .wd-root 末尾，打开时记住触发钮、把底下的工作面
    （弹层的前一个兄弟＝.wd-spread 整块）设 inert——Tab 就在弹层内打转，出不穿底层；
    关闭（点 ✕ / 点遮罩 / Esc）一律把焦点还给触发钮。 */
export function ModelSettings({ open, me, onClose, onChanged }: {
  open: boolean
  me: Me | null
  onClose: () => void
  onChanged: (p: ModelsPayload) => void
}) {
  const canEdit = me?.role === 'admin'
  const [section, setSection] = useState<'provider' | 'ui'>('provider')
  const [payload, setPayload] = useState<ModelsPayload | null>(null)
  const [draft, setDraft] = useState<ProviderDraft | null>(null)
  const [headersText, setHeadersText] = useState('')
  const [probe, setProbe] = useState<{ ok: boolean; ms: number; msg: string } | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  /* 外观四轴偏好：组件常驻（对话框页一直渲染本件），挂载即应用已存偏好——
     不打开设置也生效；选择时写回本机并立即挂到页面（系统皮肤／字体挂 <html>，
     报告皮肤在下面预览块上即时反映）。 */
  const [template, setTemplate] = useState<TemplateId>(() => readTemplate())
  const [skinSys, setSkinSys] = useState<SkinId>(() => readSkinSys())
  const [skinRpt, setSkinRpt] = useState<SkinId>(() => readSkinRpt())
  const [font, setFont] = useState<FontId>(() => readFont())

  /* 系统皮肤与字体是「全站界面」轴，挂到 <html>；挂载即生效。 */
  useEffect(() => { applySystemSkin(skinSys) }, [skinSys])
  useEffect(() => { applyFontChoice(font) }, [font])
  function pickTemplate(id: TemplateId) { setTemplate(id); writeTemplate(id) }
  function pickSkinSys(id: SkinId) { setSkinSys(id); writeSkinSys(id) }
  function pickSkinRpt(id: SkinId) { setSkinRpt(id); writeSkinRpt(id) }
  function pickFont(choice: FontId) { setFont(choice); writeFont(choice) }

  useEffect(() => {
    if (!open) return
    setSection('provider'); setMsg(''); setProbe(null); setDraft(null); setHeadersText('')
    getModels().then((p) => { setPayload(p); onChanged(p) })
      .catch((e) => setMsg(errorNote(e, '模型清单')))
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open])                                          // eslint-disable-line react-hooks/exhaustive-deps

  const presets = useMemo(() => payload?.presets ?? [], [payload])
  /* 「恢复默认模型」：编辑中的地址匹配上预置，才给这个动作（预置目录即默认目录）。 */
  const defaultModels = useMemo(
    () => presets.find((p) => p.base_url === (draft?.base_url ?? ''))?.models,
    [presets, draft?.base_url])
  /* 供应商状态位：一枚徽标一行，不写解释段落（UX §十）；说明收进悬停。 */
  const mode = providerModeOf(payload?.providers)

  const backdropRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    const under = backdropRef.current?.previousElementSibling as HTMLElement | null
    if (under) under.inert = true
    return () => {
      if (under) under.inert = false
      opener?.focus()
    }
  }, [open])

  if (!open) return null

  async function run(fn: () => Promise<ModelsPayload>) {
    setBusy(true); setMsg('')
    try {
      const p = await fn()
      setPayload(p); onChanged(p)
    } catch (e) {
      setMsg(errorNote(e, '这个操作'))
    } finally {
      setBusy(false)
    }
  }

  async function doProbe(p: { id?: string; base_url?: string; key?: string; model?: string;
                              headers?: Record<string, string> }) {
    setBusy(true); setProbe(null)
    try {
      setProbe(await testModel(p))
    } catch (e) {
      setMsg(errorNote(e, '测这一条',
        { n404: '演示服务还没更新到这一版——重启服务后再试。' }))
    } finally {
      setBusy(false)
    }
  }

  function openDraft(d: ProviderDraft, withHeaders = '') {
    setDraft(d)
    setHeadersText(withHeaders)                 // 「改」时把已存的 headers 预填回表单
    setProbe(null); setMsg('')
  }

  function submitDraft() {
    if (!draft) return
    const { headers, error } = parseHeadersText(headersText)
    if (error) { setMsg(error); return }                // 非法行保存前报错，不发请求
    void (async () => {
      setBusy(true); setMsg('')
      try {
        const p = await saveProvider({ ...draft, headers,
                                       protocol: draft.protocol || 'openai',
                                       models: draft.models ?? [] })
        setPayload(p); onChanged(p); setDraft(null); setHeadersText('')
      } catch (err) {
        setMsg(errorNote(err, '保存这条供应商'))
      } finally {
        setBusy(false)
      }
    })()
  }

  function probeDraft() {
    if (!draft) return
    const { headers, error } = parseHeadersText(headersText)
    if (error) { setMsg(error); return }
    void doProbe({ base_url: draft.base_url, key: draft.key,
                   model: (draft.models ?? []).length === 1
                     ? draft.models![0] : '',
                   headers })
  }

  return (
    <div className="mdl-modal" role="presentation" onClick={onClose} ref={backdropRef}>
      <div className="mdl-modal-in" role="dialog" aria-modal="true" aria-label="设置"
           onClick={(e) => e.stopPropagation()}>
        <header className="mdl-modal-h">
          <h2>设置</h2>
          <button type="button" className="mdl-x" onClick={onClose} aria-label="关闭">✕</button>
        </header>

        <div className="mdl-hub">
          <nav className="mdl-hub-nav" aria-label="设置分节">
            <button type="button" className={`mdl-hub-item${section === 'provider' ? ' on' : ''}`}
                    aria-pressed={section === 'provider'}
                    onClick={() => setSection('provider')}>供应商</button>
            <button type="button" className={`mdl-hub-item${section === 'ui' ? ' on' : ''}`}
                    aria-pressed={section === 'ui'}
                    onClick={() => setSection('ui')}>界面</button>
          </nav>

          <div className="mdl-hub-body">
            {section === 'provider' ? (
              <>
                {payload && (
                  <p className="mdl-mode">
                    <span className={`mdl-tag${mode === '模型模式' ? ' on' : ''}`}
                          title={mode === '模型模式'
                            ? '已有配齐的模型服务（地址、key、模型目录）'
                            : '还没有配齐的模型服务——填好一条保存即接入'}>
                      {mode}
                    </span>
                  </p>
                )}
                {!canEdit && <p className="mdl-hint">要加或改模型，请让管理员来操作。</p>}
                {canEdit && <CallStatsBlock open={open} />}

                <div className="mdl-list">
                  {(payload?.providers ?? []).map((p) => (
                    <div key={p.id || 'env'} className={`mdl-row${p.active ? ' on' : ''}`}>
                      <div className="mdl-row-main">
                        <div className="mdl-row-k">
                          {p.label}
                          {p.active && <span className="mdl-tag on">当前</span>}
                          {p.builtin && <span className="mdl-tag">部署</span>}
                          {!p.ready && <span className="mdl-tag warn">未配齐</span>}
                        </div>
                        <div className="mdl-row-v">
                          <b>{p.active_model || '—'}</b>
                          <span>{p.base_url || '未填地址'}</span>
                          <span>密钥 {p.key_hint}</span>
                          {!p.builtin && <span>{p.models.length} 个型号</span>}
                        </div>
                        {p.note && <div className="mdl-row-note">{p.note}</div>}
                      </div>
                      <div className="mdl-row-acts">
                        {!p.active && (
                          <button type="button" className="mdl-act" disabled={busy || !p.ready}
                                  title={p.active_model ? `用 ${p.active_model} 回答` : undefined}
                                  onClick={() => void run(() => setActiveModel(p.id, p.active_model))}>
                            用这个
                          </button>
                        )}
                        {canEdit && !p.builtin && (
                          <>
                            <button type="button" className="mdl-act ghost" disabled={busy}
                                    onClick={() => void doProbe({ id: p.id })}>测一下</button>
                            <button type="button" className="mdl-act ghost" disabled={busy}
                                    onClick={() => openDraft({
                                      id: p.id, label: p.label, base_url: p.base_url,
                                      key: '', note: p.note,
                                      protocol: p.protocol || 'openai',
                                      models: [...p.models],
                                      params: { ...(p.params ?? {}) },
                                    }, headersToText(p.headers))}>改</button>
                            <ConfirmButton className="mdl-act ghost" confirmText="确认删除？"
                                           disabled={busy}
                                           onConfirm={() => void run(() => removeProvider(p.id))}>
                              删
                            </ConfirmButton>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {probe && (
                  <p className={`mdl-probe ${probe.ok ? 'ok' : 'bad'}`}>
                    {probe.ok ? '✓' : '×'} {probe.msg}（{probe.ms} 毫秒）
                  </p>
                )}

                {canEdit && !draft && (
                  <div className="mdl-new">
                    <div className="mdl-presets">
                      {presets.map((p) => (
                        <button key={p.key} type="button" className="mdl-preset"
                                title="预置：地址与默认模型目录已填好，key 由你填"
                                onClick={() => openDraft({ ...EMPTY_DRAFT, label: p.label,
                                                           base_url: p.base_url,
                                                           models: [...p.models] })}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                    <button type="button" className="mdl-act"
                            onClick={() => openDraft({ ...EMPTY_DRAFT })}>
                      手动填一条
                    </button>
                  </div>
                )}

                {canEdit && draft && (
                  <ModelForm draft={draft} headersText={headersText} busy={busy}
                             defaultModels={defaultModels}
                             onDraft={setDraft} onHeadersText={setHeadersText}
                             onProbe={probeDraft} onError={setMsg}
                             onCancel={() => { setDraft(null); setProbe(null) }}
                             onSubmit={submitDraft} />
                )}
              </>
            ) : (
              <div className="mdl-ui">
                {/* 报告模板 5 选 */}
                <section className="ap-axis">
                  <div className="ap-axis-h"><b>报告模板</b><i /><em>5</em></div>
                  <div className="ap-tpl-grid" role="radiogroup" aria-label="报告模板">
                    {TEMPLATES.map((t) => (
                      <button key={t.id} type="button" role="radio"
                              aria-checked={template === t.id}
                              className={`ap-tpl${template === t.id ? ' on' : ''}`}
                              onClick={() => pickTemplate(t.id)}>
                        <span className="ap-th"><TemplateThumb id={t.id} /></span>
                        <span className="ap-tx">
                          <span className="ap-code">{t.code}</span>
                          <span className="ap-name">{t.name}</span>
                        </span>
                        <Tick />
                      </button>
                    ))}
                  </div>
                </section>

                {/* 系统皮肤 12 选：换主壳／顶栏，不影响报告纸 */}
                <section className="ap-axis">
                  <div className="ap-axis-h"><b>系统皮肤</b><i /><em>12</em></div>
                  {SKIN_GROUPS.map((grp) => (
                    <div key={grp.group} className="ap-skin-group">
                      <div className="ap-skin-gh">{grp.group}</div>
                      <div className="ap-skin-grid" role="radiogroup" aria-label={`系统皮肤·${grp.group}`}>
                        {grp.items.map((s) => (
                          <button key={s.id} type="button" role="radio"
                                  aria-checked={skinSys === s.id}
                                  title={s.name}
                                  className={`ap-skin${skinSys === s.id ? ' on' : ''}`}
                                  onClick={() => pickSkinSys(s.id)}>
                            <span className="ap-chip" style={{ background: s.accent }}>
                              <span className="ap-chip2" style={{ background: s.accent2 }} />
                            </span>
                            <span className="ap-skin-name">{s.name}</span>
                            <Tick />
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </section>

                {/* 报告皮肤 12 选：只换报告纸，不影响界面；下方纸样即时反馈 */}
                <section className="ap-axis">
                  <div className="ap-axis-h"><b>报告皮肤</b><i /><em>12</em></div>
                  <div className="ap-rpt" data-skin-rpt={skinRpt}>
                    <span className="ap-rpt-name">{SKINS.find((s) => s.id === skinRpt)?.name}</span>
                    <span className="ap-rpt-swatches">
                      <span className="ap-rpt-sw"><i className="ap-sw-paper" />纸</span>
                      <span className="ap-rpt-sw"><i className="ap-sw-ink" />墨</span>
                      <span className="ap-rpt-sw"><i className="ap-sw-accent" />主</span>
                      <span className="ap-rpt-sw"><i className="ap-sw-seal" />印</span>
                    </span>
                  </div>
                  {SKIN_GROUPS.map((grp) => (
                    <div key={grp.group} className="ap-skin-group">
                      <div className="ap-skin-gh">{grp.group}</div>
                      <div className="ap-skin-grid" role="radiogroup" aria-label={`报告皮肤·${grp.group}`}>
                        {grp.items.map((s) => (
                          <button key={s.id} type="button" role="radio"
                                  aria-checked={skinRpt === s.id}
                                  title={s.name}
                                  className={`ap-skin${skinRpt === s.id ? ' on' : ''}`}
                                  onClick={() => pickSkinRpt(s.id)}>
                            <span className="ap-chip" style={{ background: s.accent }}>
                              <span className="ap-chip2" style={{ background: s.accent2 }} />
                            </span>
                            <span className="ap-skin-name">{s.name}</span>
                            <Tick />
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </section>

                {/* 字体 6 选：系统与报告同吃一套 */}
                <section className="ap-axis">
                  <div className="ap-axis-h"><b>字体</b><i /><em>6</em></div>
                  <div className="ap-font-grid" role="radiogroup" aria-label="字体">
                    {FONTS.map((f) => (
                      <button key={f.id} type="button" role="radio"
                              aria-checked={font === f.id}
                              className={`ap-font${font === f.id ? ' on' : ''}`}
                              onClick={() => pickFont(f.id)}>
                        <span className="ap-font-name">{f.name}</span>
                        <span className="ap-font-sample"
                              style={{ fontFamily: f.title, fontSize: `calc(13px + ${f.sizeAdj})` }}>
                          文衡 · 学科监测报告
                        </span>
                        <Tick />
                      </button>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>

        {msg && <p className="mdl-err">{msg}</p>}
      </div>
    </div>
  )
}

/* ── 设置中心接线（2026-11-04 票 1）：齿轮全站常驻，接线收进这一处 hook，
   不再每页复制。用法（三页同款）：show 挂给 SideRail 的 onSettings（齿轮钮），
   node 渲染在页面根容器末尾（与问文衡现行位置同款——inert 圈禁
   依赖弹层是根容器的最后一个元素）。Ctrl+, 随齿轮走（悬停提示承诺过）；
   onChanged 给要同步模型清单的页（问文衡：设置里改完，模型菜单立刻跟上）。 */
export function useSettingsCenter(me: Me | null,
                                   onChanged?: (p: ModelsPayload) => void) {
  const [open, setOpen] = useState(false)
  const show = useCallback(() => setOpen(true), [])
  /* 本 hook 在应用根部挂载：一上来就把已存的外观偏好套到 <html>，
     馆员不打开设置也立刻生效（系统皮肤＋字体）。 */
  useEffect(() => {
    const a = readAppearance()
    applySystemSkin(a.skinSys)
    applyFontChoice(a.font)
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === ',') {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const node = (
    <ModelSettings open={open} me={me} onClose={() => setOpen(false)}
                   onChanged={onChanged ?? (() => {})} />
  )
  return { open, show, node }
}
