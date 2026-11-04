/* 模型面板（2026-10-29；2026-11-03 票 3 重构为设置中心双节 hub）：
   两件事分开——切当前模型（输入框左下「模型」菜单，谁都能点，写口在后端）、
   配置与偏好（设置弹窗，左栏两节：供应商＝管理员配模型；界面＝正文字体，人人可用）。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Me } from '../api'
import {
  getModels, removeModel, saveModel, setActiveModel, testModel,
  type ModelDraft, type ModelRow, type ModelsPayload, type ProbeResult,
} from '../api-models'
import { ConfirmButton } from '../ConfirmButton'
import { errorNote } from '../lib/status'

const EMPTY_DRAFT: ModelDraft = { label: '', base_url: '', model: '', key: '', note: '', protocol: 'openai' }

/* ── 界面节·正文字体（票 3）：三选卡片，存 localStorage、挂 <html data-font> ── */
export type FontChoice = 'serif' | 'sans' | 'kai'
export const FONT_KEY = 'wenheng.ui.font'
/** 三张字体卡（顺序即版面顺序；短说明照图四体例）。衬线＝缺省。 */
export const FONT_CHOICES: { value: FontChoice; label: string; desc: string }[] = [
  { value: 'serif', label: '衬线', desc: '适合正文阅读' },
  { value: 'sans', label: '非衬线', desc: '更接近系统界面' },
  { value: 'kai', label: '楷体', desc: '手写书卷气' },
]
/** 存储值 → 选择：读不到/不认得都回衬线（衬线是缺省＝<html> 上不挂属性）。 */
export function fontChoiceFromStorage(raw: string | null): FontChoice {
  return raw === 'sans' || raw === 'kai' ? raw : 'serif'
}
/** 把选择挂到 <html data-font>：衬线＝删属性（回缺省），其余设值。 */
export function applyFontChoice(choice: FontChoice): void {
  if (choice === 'serif') delete document.documentElement.dataset.font
  else document.documentElement.dataset.font = choice
}
function readStoredFont(): string | null {
  try { return localStorage.getItem(FONT_KEY) } catch { return null }
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
   判据＝清单里存在配齐的条目（地址/型号/key 全；含 `.env` 部署配置行）——
   只读 `/api/models` 现有字段，不新造口径、不猜字段；供应商开启后强制不回落
   的语义由后端改，界面只如实展示。规则稿模式表单照常可填（保存即「添加供应商」）。 */
export function providerModeOf(models: ModelRow[] | undefined): '模型模式' | '规则稿模式' {
  return (models ?? []).some((m) => m.ready) ? '模型模式' : '规则稿模式'
}

/** 输入框左下那颗按钮 ＋ 向上弹出的清单。 */
export function ModelMenu({ payload, busy, onPicked }: {
  payload: ModelsPayload | null
  busy: boolean
  onPicked: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const active = payload?.models.find((m) => m.active)
  const current = active?.label || '未配置模型'

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
        <span className="mdl-menu-dot" data-ready={active?.ready ? '1' : '0'} aria-hidden="true" />
        {current}
        <span className="mdl-caret" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="mdl-menu" role="menu">
          {(payload?.models ?? []).map((m) => (
            <button key={m.id || 'env'} type="button" role="menuitemradio"
                    aria-checked={m.active} disabled={!m.ready}
                    className={`mdl-menu-item${m.active ? ' on' : ''}`}
                    title={m.ready ? `${m.model} · ${m.base_url}` : '这条还没配齐（地址/型号/key）'}
                    onClick={() => { setOpen(false); if (!m.active) onPicked(m.id) }}>
              <span className="mdl-menu-k">{m.label}</span>
              <span className="mdl-menu-v">{m.model || '—'}{!m.ready && ' · 未配齐'}</span>
              {m.active && <span className="mdl-menu-tick" aria-hidden="true">✓</span>}
            </button>
          ))}
          {!payload && <p className="mdl-menu-cap">正在读模型清单…</p>}
        </div>
      )}
    </div>
  )
}

/** 新增/编辑表单（票 3 图五字段序）：名称 / Base URL / API Key（留空＝不改）/ 模型 /
    Headers（可选，多行 K=V）/ API 协议（单选 OpenAI Compatible）；备注殿后（卡片上还显示它，
    后端保存会把缺省的备注清掉——去了这格，改一次就把原备注抹了）。 */
export function ModelForm({ draft, headersText, busy, onDraft, onHeadersText, onProbe, onCancel, onSubmit }: {
  draft: ModelDraft
  headersText: string
  busy: boolean
  onDraft: (d: ModelDraft) => void
  onHeadersText: (t: string) => void
  onProbe: () => void
  onCancel: () => void
  onSubmit: () => void
}) {
  return (
    <form className="mdl-form" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <p className="mdl-hint">{draft.id ? `修改「${draft.label}」` : '新增一条模型'}</p>
      <label>名称<input value={draft.label} placeholder="例如 MiniMax M2.7"
              onChange={(e) => onDraft({ ...draft, label: e.target.value })} /></label>
      <label>Base URL<input value={draft.base_url} placeholder="服务商给的接口地址，一般以 v1 结尾"
              onChange={(e) => onDraft({ ...draft, base_url: e.target.value })} /></label>
      <label>API Key<input value={draft.key} type="password" autoComplete="off"
              placeholder={draft.id ? '留空＝不改原来那把' : 'sk-…'}
              onChange={(e) => onDraft({ ...draft, key: e.target.value })} /></label>
      <label>模型<input value={draft.model} placeholder="MiniMax/MiniMax-M2.7"
              onChange={(e) => onDraft({ ...draft, model: e.target.value })} /></label>
      <label>Headers（可选）<textarea rows={3} value={headersText}
              placeholder={'每行一条：名字=值（空行忽略）\n例如 X-Org=ynu'}
              onChange={(e) => onHeadersText(e.target.value)} /></label>
      <label>API 协议<select value={draft.protocol ?? 'openai'}
              onChange={(e) => onDraft({ ...draft, protocol: e.target.value })}>
        <option value="openai">OpenAI Compatible</option>
      </select></label>
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
  const [draft, setDraft] = useState<ModelDraft | null>(null)
  const [headersText, setHeadersText] = useState('')
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  /* 界面节·字体偏好：组件常驻（对话框页一直渲染本件），挂载即应用已存偏好——
     不打开设置也生效；选择时写回 localStorage 并立即挂 <html data-font>。 */
  const [font, setFont] = useState<FontChoice>(() => fontChoiceFromStorage(readStoredFont()))
  useEffect(() => { applyFontChoice(font) }, [font])
  function pickFont(choice: FontChoice) {
    setFont(choice)
    try { localStorage.setItem(FONT_KEY, choice) } catch { /* 存不下＝只这次会话内生效 */ }
  }

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
  /* 供应商状态位：一枚徽标一行，不写解释段落（UX §十）；说明收进悬停。 */
  const mode = providerModeOf(payload?.models)

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
      setMsg(errorNote(e, '测这一条'))
    } finally {
      setBusy(false)
    }
  }

  function openDraft(d: ModelDraft, withHeaders = '') {
    setDraft(d)
    setHeadersText(withHeaders)                 // 「改」时把已存的 headers 预填回表单
    setProbe(null); setMsg('')
  }

  function submitDraft() {
    if (!draft) return
    if (!draft.model.trim()) { setMsg('型号不能为空'); return }
    const { headers, error } = parseHeadersText(headersText)
    if (error) { setMsg(error); return }                // 非法行保存前报错，不发请求
    void (async () => {
      setBusy(true); setMsg('')
      try {
        const p = await saveModel({ ...draft, headers, protocol: draft.protocol || 'openai' })
        setPayload(p); onChanged(p); setDraft(null); setHeadersText('')
      } catch (err) {
        setMsg(errorNote(err, '保存这条模型'))
      } finally {
        setBusy(false)
      }
    })()
  }

  function probeDraft() {
    if (!draft) return
    const { headers, error } = parseHeadersText(headersText)
    if (error) { setMsg(error); return }
    void doProbe({ base_url: draft.base_url, key: draft.key, model: draft.model, headers })
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
                            ? '已有配齐的模型服务（地址、型号、key）'
                            : '还没有配齐的模型服务——填好一条保存即接入'}>
                      {mode}
                    </span>
                  </p>
                )}
                {!canEdit && <p className="mdl-hint">要加或改模型，请让管理员来操作。</p>}

                <div className="mdl-list">
                  {(payload?.models ?? []).map((m) => (
                    <div key={m.id || 'env'} className={`mdl-row${m.active ? ' on' : ''}`}>
                      <div className="mdl-row-main">
                        <div className="mdl-row-k">
                          {m.label}
                          {m.active && <span className="mdl-tag on">当前</span>}
                          {m.builtin && <span className="mdl-tag">部署</span>}
                          {!m.ready && <span className="mdl-tag warn">未配齐</span>}
                        </div>
                        <div className="mdl-row-v">
                          <b>{m.model || '—'}</b>
                          <span>{m.base_url || '未填地址'}</span>
                          <span>密钥 {m.key_hint}</span>
                        </div>
                        {m.note && <div className="mdl-row-note">{m.note}</div>}
                      </div>
                      <div className="mdl-row-acts">
                        {!m.active && (
                          <button type="button" className="mdl-act" disabled={busy || !m.ready}
                                  onClick={() => void run(() => setActiveModel(m.id))}>用这个</button>
                        )}
                        {canEdit && !m.builtin && (
                          <>
                            <button type="button" className="mdl-act ghost" disabled={busy}
                                    onClick={() => void doProbe({ id: m.id })}>测一下</button>
                            <button type="button" className="mdl-act ghost" disabled={busy}
                                    onClick={() => openDraft({
                                      id: m.id, label: m.label, base_url: m.base_url,
                                      model: m.model, key: '', note: m.note,
                                      protocol: m.protocol || 'openai',
                                    }, headersToText(m.headers))}>改</button>
                            <ConfirmButton className="mdl-act ghost" confirmText="确认删除？"
                                           disabled={busy}
                                           onConfirm={() => void run(() => removeModel(m.id))}>删</ConfirmButton>
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
                                onClick={() => openDraft({ ...EMPTY_DRAFT, label: p.label,
                                                           base_url: p.base_url, model: p.models[0] })}>
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
                             onDraft={setDraft} onHeadersText={setHeadersText}
                             onProbe={probeDraft}
                             onCancel={() => { setDraft(null); setProbe(null) }}
                             onSubmit={submitDraft} />
                )}
              </>
            ) : (
              <div className="mdl-ui">
                <div className="mdl-font-cards" role="radiogroup" aria-label="正文字体">
                  {FONT_CHOICES.map((c) => (
                    <button key={c.value} type="button" role="radio"
                            aria-checked={font === c.value}
                            className={`mdl-font-card${font === c.value ? ' on' : ''}`}
                            data-font={c.value}
                            onClick={() => pickFont(c.value)}>
                      <b>{c.label}</b>
                      <span>{c.desc}</span>
                    </button>
                  ))}
                </div>
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
