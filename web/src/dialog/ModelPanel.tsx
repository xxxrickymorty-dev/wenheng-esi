/* 模型面板（2026-10-29）：输入框左下那颗「模型」按钮 ＋ 设置里的模型清单。
   两件事分开：切当前模型（谁都能点，写口在后端）、配模型（只有管理员，写口也在后端）。 */

import { useEffect, useMemo, useState } from 'react'
import type { Me } from '../api'
import {
  getModels, removeModel, saveModel, setActiveModel, testModel,
  type ModelDraft, type ModelsPayload, type ProbeResult,
} from '../api-models'
import { ConfirmButton } from '../ConfirmButton'
import { errorNote } from '../lib/status'

const EMPTY_DRAFT: ModelDraft = { label: '', base_url: '', model: '', key: '', note: '' }

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

/** 设置弹层：清单 ＋ 新增/编辑表单 ＋ 探活。 */
export function ModelSettings({ open, me, onClose, onChanged }: {
  open: boolean
  me: Me | null
  onClose: () => void
  onChanged: (p: ModelsPayload) => void
}) {
  const canEdit = me?.role === 'admin'
  const [payload, setPayload] = useState<ModelsPayload | null>(null)
  const [draft, setDraft] = useState<ModelDraft | null>(null)
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setMsg(''); setProbe(null); setDraft(null)
    getModels().then((p) => { setPayload(p); onChanged(p) })
      .catch((e) => setMsg(errorNote(e, '模型清单')))
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open])                                          // eslint-disable-line react-hooks/exhaustive-deps

  const presets = useMemo(() => payload?.presets ?? [], [payload])

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

  async function doProbe(p: { id?: string; base_url?: string; key?: string; model?: string }) {
    setBusy(true); setProbe(null)
    try {
      setProbe(await testModel(p))
    } catch (e) {
      setMsg(errorNote(e, '测这一条'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mdl-modal" role="presentation" onClick={onClose}>
      <div className="mdl-modal-in" role="dialog" aria-modal="true" aria-label="模型设置"
           onClick={(e) => e.stopPropagation()}>
        <header className="mdl-modal-h">
          <h2>模型设置</h2>
          <button type="button" className="mdl-x" onClick={onClose} aria-label="关闭">✕</button>
        </header>
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
                            onClick={() => {
                              setDraft({ id: m.id, label: m.label, base_url: m.base_url,
                                         model: m.model, key: '', note: m.note })
                              setProbe(null); setMsg('')
                            }}>改</button>
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
                        onClick={() => setDraft({ ...EMPTY_DRAFT, label: p.label,
                                                  base_url: p.base_url, model: p.models[0] })}>
                  {p.label}
                </button>
              ))}
            </div>
            <button type="button" className="mdl-act" onClick={() => setDraft({ ...EMPTY_DRAFT })}>
              手动填一条
            </button>
          </div>
        )}

        {canEdit && draft && (
          <form className="mdl-form" onSubmit={(e) => {
            e.preventDefault()
            if (!draft.model.trim()) { setMsg('型号不能为空'); return }
            void (async () => {
              setBusy(true); setMsg('')
              try {
                const p = await saveModel(draft)
                setPayload(p); onChanged(p); setDraft(null)
              } catch (err) {
                setMsg(errorNote(err, '保存这条模型'))
              } finally {
                setBusy(false)
              }
            })()
          }}>
            <p className="mdl-hint">{draft.id ? `修改「${draft.label}」` : '新增一条模型'}</p>
            <label>名字<input value={draft.label} placeholder="例如 MiniMax M2.7"
                    onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></label>
            <label>接口地址<input value={draft.base_url} placeholder="服务商给的接口地址，一般以 v1 结尾"
                    onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} /></label>
            <label>型号<input value={draft.model} placeholder="MiniMax/MiniMax-M2.7"
                    onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label>
            <label>密钥<input value={draft.key} type="password" autoComplete="off"
                    placeholder={draft.id ? '留空＝不改原来那把' : 'sk-…'}
                    onChange={(e) => setDraft({ ...draft, key: e.target.value })} /></label>
            <label>备注<input value={draft.note ?? ''} placeholder="给馆员看的一句话"
                    onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></label>
            <div className="mdl-form-acts">
              <button type="submit" className="mdl-act primary" disabled={busy}>保存</button>
              <button type="button" className="mdl-act ghost" disabled={busy}
                      onClick={() => void doProbe({ base_url: draft.base_url,
                                                    key: draft.key, model: draft.model })}>
                先测一下
              </button>
              <button type="button" className="mdl-act ghost" onClick={() => { setDraft(null); setProbe(null) }}>
                取消
              </button>
            </div>
          </form>
        )}

        {msg && <p className="mdl-err">{msg}</p>}
      </div>
    </div>
  )
}
