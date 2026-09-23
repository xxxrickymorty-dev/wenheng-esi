/* 审核台（工作区 3）——把「可签发」这件事做成可操作的。
   契约 §2.2 #7/#8；后端 Batch 3/4 已交付 sign/revoke/flag 的 JSON 版。
   🔴 前端只是入口，**真正的门在后端**（require_admin）；这里按角色隐藏只是不打扰人。
   在线填（fill）需要 todo 列表，后端目前只有服务端渲染页——没有 GET，所以此处如实标注。 */

import { useEffect, useState } from 'react'
import type { Me, Period } from './api'
import { getCollation, type CollationRow } from './api2'
import { flagLoc, revokePeriod, signPeriod } from './api3'
import { Icon } from './icons'

export function Review({
  period, me, periods, onChanged,
}: {
  period: string | null
  me: Me | null
  periods: Period[]
  onChanged: () => void
}) {
  const [note, setNote] = useState('')
  const [known, setKnown] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [col, setCol] = useState<CollationRow[] | null>(null)
  const [nDoubt, setNDoubt] = useState<number | null>(null)

  const row = periods.find((p) => p.period === period) ?? null
  const status = row?.status ?? 'unsigned'
  const isAdmin = me?.role === 'admin'

  useEffect(() => {
    if (!period) return
    let alive = true
    setCol(null); setMsg(null); setNDoubt(null)
    getCollation(period).then((c) => { if (alive) setCol(c) }).catch(() => { if (alive) setCol([]) })
    return () => { alive = false }
  }, [period])

  async function doSign() {
    if (!period) return
    setBusy(true); setMsg(null)
    try {
      const r = await signPeriod(period, { known: known, note })
      setMsg({ ok: true, text: `已签单（状态 ${r.status}）` })
      onChanged()
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setMsg({
        ok: false,
        text: h.status === 409
          ? `闸门没放行：${h.body?.error ?? '服务端拒绝了这次签单'}`
          : h.body?.error ?? h.message ?? '签单失败',
      })
    } finally { setBusy(false) }
  }

  async function doRevoke() {
    if (!period) return
    setBusy(true); setMsg(null)
    try {
      const r = await revokePeriod(period, note)
      setMsg({ ok: true, text: `已撤回（状态 ${r.status}）` })
      onChanged()
    } catch (e) {
      const h = e as { body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '撤回失败' })
    } finally { setBusy(false) }
  }

  async function doFlag(loc: string) {
    if (!period) return
    try {
      const r = await flagLoc(period, loc)
      setNDoubt(r.n_doubt)
      setMsg({ ok: true, text: `${loc} → ${r.state === 'doubt' ? '已标存疑' : '已取消存疑'}` })
    } catch (e) {
      const h = e as { body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '标记失败' })
    }
  }

  const manual = (col ?? []).filter((r) => r.manual)

  return (
    <>
      <section className="card" style={{ padding: '22px 24px' }}>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="seal" size={22} />审核 · 签单
          <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
          <span className={`pill ${status === 'signed' ? 'signed' : status === 'stale' ? 'stale' : 'unsigned'}`}
                style={{ marginLeft: 'auto' }}>
            {status === 'signed' ? '已签发' : status === 'stale' ? '签名已失效' : '未签发'}
          </span>
        </h2>

        {!isAdmin && (
          <div className="pending-box" style={{ marginTop: 14 }}>
            当前角色{me ? `（${me.role}）` : '未知'}不能审核——签单需要管理员权限。
            这是后端 `require_admin` 挡的，不是前端藏起来的。
          </div>
        )}

        <p className="hint" style={{ marginTop: 12 }}>
          签单会绑在这一版的指纹上：流水线重跑一次报告就变了，签名会自动失效并提示重签。
        </p>

        <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginTop: 14 }}>
          <input type="checkbox" checked={known} onChange={(e) => setKnown(e.target.checked)} disabled={!isAdmin} />
          <span>
            我已逐项看过<b>待人工</b>与<b>存疑</b>处
            {manual.length > 0 ? `（本期待人工 ${manual.length} 处）` : ''}，同意放行。
          </span>
        </label>

        <div style={{ marginTop: 12 }}>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="批注（可选）：这一版为什么可以签发、还有哪些已知问题"
            rows={3}
            disabled={!isAdmin}
            style={{
              width: '100%', font: 'inherit', padding: '10px 12px', color: 'inherit',
              border: '1px solid var(--line)', borderRadius: 10, background: 'var(--card)',
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
          <button className="btn primary" onClick={doSign}
                  disabled={!isAdmin || busy || !period || status === 'signed'}>
            <Icon name="seal" size={20} />钤印签单
          </button>
          <button className="btn" onClick={doRevoke}
                  disabled={!isAdmin || busy || status === 'unsigned'}>
            <Icon name="refresh" size={19} />撤回
          </button>
          {msg && (
            <span className="hint" style={{ color: msg.ok ? 'var(--ok)' : 'var(--bad)' }}>
              {msg.text}
            </span>
          )}
        </div>
      </section>

      <section className="card" style={{ marginTop: 18, padding: '20px 24px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="alert" size={20} />待人工处 · 标存疑
          {nDoubt != null && <span className="hint" style={{ fontWeight: 400 }}>本页操作后存疑 {nDoubt} 处</span>}
        </h2>
        {col == null ? (
          <div className="pending-box">正在读对勘……</div>
        ) : manual.length === 0 ? (
          <div className="pending-box">这一期没有标「待人工」的地方（后端 collation 的 manual 都是 false）。</div>
        ) : (
          <div style={{ marginTop: 12 }}>
            {manual.slice(0, 12).map((r) => (
              <div key={r.section + r.loc}
                   style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '9px 0',
                            borderBottom: '1px solid var(--line-2)' }}>
                <span className="mono" style={{ flex: '0 0 150px', color: 'var(--ink-3)', fontSize: 13.5 }}>
                  {r.loc}
                </span>
                <span style={{ flex: 1, color: 'var(--ink-2)', fontSize: 14.5 }}>
                  {(r.oldPreview || r.old) ? `原：${r.oldPreview ?? r.old}` : '（母版此处为空）'}
                  {r.source ? ` · 来源 ${r.source}` : ''}
                </span>
                <button className="btn" style={{ padding: '6px 12px', fontSize: 14 }}
                        onClick={() => doFlag(r.loc)} disabled={!isAdmin}>
                  标存疑
                </button>
              </div>
            ))}
            {manual.length > 12 && (
              <p className="hint" style={{ marginTop: 10 }}>
                另有 {manual.length - 12} 处，完整清单见「红色件清单」。
              </p>
            )}
          </div>
        )}
      </section>

      <section className="card" style={{ marginTop: 18, padding: '20px 24px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="doc" size={20} />在线填（待接口）
        </h2>
        <div className="pending-box" style={{ marginTop: 12 }}>
          <b>缺一个 GET</b>：填表的 todo 列表目前只在服务端渲染页里（`workbench.build()`），
          没有 JSON 端点——前端拿不到 todo_id。建议加
          <code> GET /api/periods/&#123;期次&#125;/workbench</code>（返回 todos / fills / flags），
          接上之后这一块就能像签单一样可用。
        </div>
      </section>
    </>
  )
}
