/* 审核台（工作区 3）——把「可签发」这件事做成可操作的。
   契约 §2.2 #7/#8；后端 Batch 3/4 已交付 sign/revoke/flag 的 JSON 版。
   🔴 前端只是入口，**真正的门在后端**（require_admin）；这里按角色隐藏只是不打扰人。
   在线填也是真数据了：GET workbench（todo/fills）+ POST fill（批量补录）。 */

import { useEffect, useState } from 'react'
import type { Me, Period } from './api'
import { getCollation, type CollationRow } from './api2'
import { flagLoc, revokePeriod, signPeriod } from './api3'
import { req } from './api'
import { getWorkbench, postFill, type TodoItem, type WorkbenchData } from './api4'
import { ConfirmButton } from './ConfirmButton'
import { Icon } from './icons'

/** 在线填：真数据（GET /api/periods/{p}/workbench）+ 批量补录（POST .../fill）。
    后端口径：只写产物目录里的填写记录，**台账一个字节不动**——填的是报告，不是数据源。 */
function FillSection({ period, isAdmin }: { period: string | null; isAdmin: boolean }) {
  const [wb, setWb] = useState<WorkbenchData | null>(null)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [note, setNote] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  useEffect(() => {
    if (!period) return
    let alive = true
    setWb(null); setNote(null); setMsg(null); setVals({})
    getWorkbench(period)
      .then((x) => {
        if (!alive) return
        setWb(x)
        const v: Record<string, string> = {}
        for (const t of x.todo_fill) if (t.filled) v[t.id] = t.filled
        setVals(v)
      })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setNote(
          e.status === 403 ? '在线填需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有工作台数据。'
              : '读工作台数据失败。',
        )
      })
    return () => { alive = false }
  }, [period])

  async function save() {
    if (!period || !wb) return
    const items: Record<string, string> = {}
    for (const [k, v] of Object.entries(vals)) if (v.trim()) items[k] = v
    if (Object.keys(items).length === 0) {
      setMsg({ ok: false, text: '还没有填写任何一处。' })
      return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await postFill(period, items)
      setMsg({ ok: true, text: `已保存 ${r.saved} 处` })
      setWb(await getWorkbench(period))
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '保存失败' })
    } finally { setBusy(false) }
  }

  /* 填完重出：把填值交给后端，撤下旧成品（进 _superseded/，能回滚）再重出报告。
     后端口径：不重新解析台账，2–15 秒（重插图），同步阻塞——所以按钮要挡住重复点。 */
  async function rebuild() {
    if (!period || !wb) return
    const items: Record<string, string> = {}
    for (const [k, v] of Object.entries(vals)) if (v.trim()) items[k] = v
    setRebuilding(true); setMsg(null)
    try {
      const r = await req<Record<string, unknown>>(
        `/api/periods/${encodeURIComponent(period)}/rebuild`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) },
      )
      const saved = typeof r?.saved === 'number' ? `已带上 ${r.saved} 处填值 · ` : ''
      setMsg({ ok: true, text: `${saved}报告已重出（旧成品已撤到 _superseded/）——回报告屏可看新版` })
      setWb(await getWorkbench(period))
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ ok: false, text: (h.body?.error ?? h.message ?? '重出失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally { setRebuilding(false) }
  }

  const row2 = (t: TodoItem, withInput: boolean) => (
    <div key={t.id} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '9px 0',
                            borderBottom: '1px solid var(--line-2)' }}>
      <span className="mono" style={{ flex: '0 0 160px', color: 'var(--ink-3)', fontSize: 13.5 }}>
        {t.where}
      </span>
      <span style={{ flex: '0 0 200px', fontSize: 14.5 }}>
        {t.title}
        <br />
        <span className="hint" style={{ fontSize: 12.5 }}>来自 {t.source}</span>
      </span>
      {withInput ? (
        <input
          type="text"
          value={vals[t.id] ?? ''}
          placeholder={t.filled ? '' : '填在这里'}
          onChange={(e) => setVals((s) => ({ ...s, [t.id]: e.target.value }))}
          disabled={!isAdmin || busy}
          style={{ flex: 1, font: 'inherit', padding: '7px 10px', color: 'inherit',
                   border: '1px solid var(--line)', borderRadius: 8, background: 'var(--card)' }}
        />
      ) : (
        <span className="hint" style={{ flex: 1 }}>（待你核过再定）</span>
      )}
    </div>
  )

  return (
    <>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="doc" size={20} />在线填 · 报告里的空
        {wb && (
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            （待补录 {wb.todo_fill.length} 处 · 待确认 {wb.todo_confirm.length} 处 · 已存 {wb.n_filled} 处）
          </span>
        )}
      </h2>
      <p className="hint" style={{ marginTop: 8 }}>
        填的是报告里的空，<b>台账一个字节都不动</b>。
        {wb && wb.traceable.n > 0 && (
          <> 本期 {wb.traceable.n} 个数字，{wb.traceable.with_source} 个标了出处。</>
        )}
      </p>

      {note ? (
        <div className="pending-box" style={{ marginTop: 12 }}>{note}</div>
      ) : !wb ? (
        <div className="pending-box" style={{ marginTop: 12 }}>正在读待办……</div>
      ) : wb.todo_fill.length === 0 && wb.todo_confirm.length === 0 ? (
        <div className="pending-box" style={{ marginTop: 12 }}>这一期没有要人填的地方。</div>
      ) : (
        <>
          <div style={{ marginTop: 8 }}>{wb.todo_fill.map((t) => row2(t, true))}</div>

          {wb.todo_confirm.length > 0 && (
            <>
              <h3 style={{ fontSize: 16, marginTop: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name="alert" size={17} />待确认（{wb.todo_confirm.length} 处）
              </h3>
              <div>{wb.todo_confirm.map((t) => row2(t, false))}</div>
            </>
          )}

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
            <button className="btn primary" onClick={save} disabled={!isAdmin || busy || rebuilding}>
              <Icon name="doc" size={19} />保存填写
            </button>
            <ConfirmButton className="btn" disabled={!isAdmin || busy || rebuilding}
                           confirmText="确认重出？旧版会先撤下"
                           title="把填值交给后端重出报告；旧版会先撤下、可回滚，约 2–15 秒"
                           onConfirm={rebuild}>
              <Icon name="refresh" size={19} />{rebuilding ? '正在重出……' : '保存并重出报告'}
            </ConfirmButton>
            {msg && (
              <span className="hint" style={{ color: msg.ok ? 'var(--ok)' : 'var(--bad)' }}>{msg.text}</span>
            )}
          </div>

          {/* 已填列表：谁填的、什么时候（数据来自 workbench 的 todo_fill，后端字段直出） */}
          {wb.todo_fill.some((t) => t.filled) && (
            <>
              <h3 style={{ fontSize: 16, marginTop: 16 }}>已填（{wb.todo_fill.filter((t) => t.filled).length} 处）</h3>
              <div>
                {wb.todo_fill.filter((t) => t.filled).map((t) => (
                  <div key={`f-${t.id}`} style={{ display: 'flex', gap: 12, alignItems: 'baseline',
                                                padding: '8px 0', borderBottom: '1px solid var(--line-2)' }}>
                    <span className="mono" style={{ flex: '0 0 160px', color: 'var(--ink-3)', fontSize: 13.5 }}>{t.where}</span>
                    <span style={{ flex: '0 0 180px', fontSize: 14.5 }}>{t.title}</span>
                    <b style={{ flex: 1, color: 'var(--zhu)' }}>{t.filled}</b>
                    <span className="hint" style={{ fontSize: 12.5 }}>
                      {t.filled_by ?? '—'}{t.filled_at ? ` · ${t.filled_at}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}

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
    /* 全量：签单前要看的「待人工/待确认」清单不能只剩分页前 50 行（会漏审） */
    getCollation(period, true).then((c) => { if (alive) setCol(c) }).catch(() => { if (alive) setCol([]) })
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
          <ConfirmButton className="btn" disabled={!isAdmin || busy || status === 'unsigned'}
                         confirmText="确认撤回？签名会失效" onConfirm={doRevoke}>
            <Icon name="refresh" size={19} />撤回
          </ConfirmButton>
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
        <FillSection period={period} isAdmin={isAdmin} />
      </section>
    </>
  )
}
