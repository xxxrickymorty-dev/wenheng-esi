/* 审核台（工作区 3）——"报告形态"的复核（2026-09-28 rick 定）：
   整篇试排报告从头到尾铺开、报告里的空就地填、签单与下载同屏。
   退出「对勘本 / T19-r2c0 / extract_province」那一套技术行话——那是审计视图（读报屏 → 对勘本）。

   数据三路：
   - GET report-preview：docx 全文块 + 报告里的空（id 与工作台同一套键）；
   - GET workbench：填写记录 / 存疑状态；
   - GET facts：数据核对读数。
   🔴 真门在后端：签单 / 重出 / 下载都由后端闸门把关，前端只把它们摆到顺手的位置。 */

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { Me, Period } from './api'
import { getFacts } from './api4'
import { flagLoc, revokePeriod, signPeriod } from './api3'
import { getWorkbench, postFill, type WorkbenchData } from './api4'
import {
  getReportPreview, rebuildPeriod, reportImageUrl,
  type PreviewBlock, type PreviewSeg, type ReportPreview,
} from './api6'
import { ConfirmButton } from './ConfirmButton'
import { Icon } from './icons'

type Msg = { ok: boolean; text: string } | null

/** 段落里的片段：文字按 docx 的字号/加粗呈现；空位就地变输入框（宽随内容长）。 */
function Runs({
  segs, vals, onVal, disabled,
}: {
  segs: PreviewSeg[]
  vals: Record<string, string>
  onVal: (id: string, v: string) => void
  disabled: boolean
}) {
  return (
    <>
      {segs.map((seg, i) => {
        if ('ph' in seg) {
          const v = vals[seg.ph] ?? ''
          const w = Math.min(26, Math.max(9, ((v || seg.title || '').length) + 5))
          return (
            <input
              key={`ph-${i}`}
              id={`rv-ph-${seg.ph}`}
              className={`rv-in${v.trim() ? ' filled' : ''}`}
              value={v}
              placeholder={seg.title}
              title={seg.title}
              aria-label={seg.title}
              disabled={disabled}
              style={{ width: `${w}em` }}
              onChange={(e) => onVal(seg.ph, e.target.value)}
            />
          )
        }
        const style: CSSProperties = {}
        if (seg.size) style.fontSize = `${seg.size}pt`
        const text = seg.t
        return <span key={`t-${i}`} style={style}>{seg.b ? <b>{text}</b> : text}</span>
      })}
    </>
  )
}

/** 一个块：段落 / 表格（可带图）/ 插图。全部按 docx 原顺序、原内容。 */
function BlockView({
  block, vals, onVal, disabled, period,
}: {
  block: PreviewBlock
  vals: Record<string, string>
  onVal: (id: string, v: string) => void
  disabled: boolean
  period: string
}) {
  if (block.t === 'p') {
    const cls = `rv-para${block.align === 'center' ? ' rv-center' : ''}`
    const ta = block.align && block.align !== 'justify'
      ? ({ textAlign: block.align } as CSSProperties) : undefined
    return (
      <p className={cls} style={ta}>
        <Runs segs={block.runs} vals={vals} onVal={onVal} disabled={disabled} />
      </p>
    )
  }
  if (block.t === 'img') {
    return (
      <p className="rv-img">
        <img src={reportImageUrl(period, block.rid)} alt="报告插图" loading="lazy"
             style={block.w_cm ? { width: `${Math.round(block.w_cm * 37.8)}px` } : undefined} />
      </p>
    )
  }
  return (
    <div className="rv-tblwrap">
      <table>
        <tbody>
          {block.rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} colSpan={cell.span || undefined}>
                  {cell.text}
                  {(cell.imgs ?? []).map((rid) => (
                    <img key={rid} src={reportImageUrl(period, rid)} alt="图表" loading="lazy" />
                  ))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  const [preview, setPreview] = useState<ReportPreview | null>(null)
  const [previewNote, setPreviewNote] = useState<string | null>(null)
  const [wb, setWb] = useState<WorkbenchData | null>(null)
  const [wbNote, setWbNote] = useState<string | null>(null)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [assertions, setAssertions] = useState<{ total: number; fail: number } | null>(null)
  const [note, setNote] = useState('')
  const [known, setKnown] = useState(false)
  const [busy, setBusy] = useState<null | 'sign' | 'rebuild' | 'save' | 'revoke'>(null)
  const [msg, setMsg] = useState<Msg>(null)
  // 「跳到下一处」的游标：连点就按报告顺序依次落到每个空位（填完一处自动跳过）
  const [cursor, setCursor] = useState(0)
  // 「只看存疑」筛选（票 14）：签字前一眼定位标过的处
  const [onlyDoubt, setOnlyDoubt] = useState(false)

  const row = periods.find((p) => p.period === period) ?? null
  const status = row?.status ?? 'unsigned'
  const isAdmin = me?.role === 'admin'

  useEffect(() => {
    if (!period) return
    let alive = true
    setPreview(null); setPreviewNote(null); setWb(null); setWbNote(null)
    setVals({}); setMsg(null); setKnown(false); setAssertions(null); setNote(''); setOnlyDoubt(false)

    getReportPreview(period)
      .then((pv) => { if (alive) setPreview(pv) })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setPreviewNote(
          e.status === 403 ? '审核台需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有出稿。'
              : '读试排报告失败（服务没有回应）。',
        )
      })
    getWorkbench(period)
      .then((w) => {
        if (!alive) return
        setWb(w)
        const v: Record<string, string> = {}
        for (const t of w.todo_fill) if (t.filled?.trim()) v[t.id] = t.filled
        setVals(v)
      })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setWbNote(e.status === 403 ? '填写数据需要管理员权限。' : '读填写数据失败。')
      })
    getFacts(period)
      .then((f) => { if (alive) setAssertions(f.assertions) })
      .catch(() => { /* 读数取不到就不显示，不编 */ })
    return () => { alive = false }
  }, [period])

  async function refreshPreview() {
    if (!period) return
    setPreview(await getReportPreview(period))
  }

  async function refreshWb() {
    if (!period) return
    const w = await getWorkbench(period)
    setWb(w)
    setWbNote(null)
    const v: Record<string, string> = {}
    for (const t of w.todo_fill) if (t.filled?.trim()) v[t.id] = t.filled
    setVals(v)
  }

  const fields = useMemo(() => Object.entries(preview?.fields ?? {}), [preview])
  const nField = fields.length
  // 未填的空（按报告顺序）：清单高亮、「下一处」跳转、计数共用这一份
  const emptyIds = useMemo(
    () => fields.filter(([id]) => !(vals[id] ?? '').trim()).map(([id]) => id),
    [fields, vals],
  )
  const nLeft = emptyIds.length

  /* 从报告页「去补 →」进来带 focus（=空位的 where，如「正文/p1」）：
     滚到并聚焦对应输入框（票 14）。 */
  useEffect(() => {
    if (!preview || !period) return
    const focus = new URLSearchParams(window.location.search).get('focus')
    if (!focus) return
    const idx = fields.findIndex(([, meta]) => meta.where === focus)
    if (idx < 0) return
    const t = window.setTimeout(() => jumpTo(fields[idx][0]), 350)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, period, fields])

  const fills = wb?.fills_list ?? []
  const pendingN = fills.filter((f) => f.state === 'pending').length
  const appliedN = fills.filter((f) => f.state === 'applied').length
  const doubt = wb?.review ?? {}
  const doubtN = wb?.n_doubt ?? Object.keys(doubt).length
  /* 「知悉」要确认的对象：报告里的空 + 已标存疑（有其一，未勾选就不能签） */
  const needAck = nField > 0 || doubtN > 0
  const fieldsShown = onlyDoubt ? fields.filter(([, meta]) => !!doubt[meta.where]) : fields

  function collectItems(): Record<string, string> {
    const items: Record<string, string> = {}
    for (const [k, v] of Object.entries(vals)) if (v.trim()) items[k] = v.trim()
    return items
  }

  function dirty(): boolean {
    if (!wb) return Object.keys(collectItems()).length > 0
    const saved: Record<string, string> = {}
    for (const t of wb.todo_fill) saved[t.id] = (t.filled ?? '').trim()
    for (const [k, v] of Object.entries(vals)) {
      if (v.trim() !== (saved[k] ?? '')) return true
    }
    return false
  }

  async function doSave() {
    if (!period || !wb) return
    const items = collectItems()
    if (Object.keys(items).length === 0) {
      setMsg({ ok: false, text: '还没有填写任何一处。' })
      return
    }
    setBusy('save'); setMsg(null)
    try {
      const r = await postFill(period, items)
      setMsg({ ok: true, text: `已保存 ${r.saved} 处（还没写进报告——点「保存并重出报告」才写入）` })
      await refreshWb()
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '保存失败' })
    } finally { setBusy(null) }
  }

  async function doRebuild() {
    if (!period || !wb) return
    const items = collectItems()
    if (Object.keys(items).length === 0) {
      setMsg({ ok: false, text: '还没有填写任何一处。' })
      return
    }
    setBusy('rebuild'); setMsg(null)
    try {
      const r = await rebuildPeriod(period, items)
      setMsg({ ok: true, text: `报告已重出（用时 ${r.elapsed} 秒，旧稿留档可回滚）——填的值已写进正文` })
      await refreshPreview()
      await refreshWb()
      onChanged()
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ ok: false, text: (h.body?.error ?? h.message ?? '重出失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally { setBusy(null) }
  }

  /* 签单 = 「把已填的写进报告（如果有）→ 签」一步完成。
     防的就是 2026-09-28 rick 踩的那次：填了日期直接签，下载的稿里没有日期。 */
  async function doSign() {
    if (!period) return
    const items = collectItems()
    const needRebuild = pendingN > 0 || (dirty() && Object.keys(items).length > 0)
    setBusy('sign'); setMsg(null)
    try {
      if (needRebuild) {
        setMsg({ ok: true, text: '正在把填的值写进报告……' })
        const r = await rebuildPeriod(period, items)
        setMsg({ ok: true, text: `已把填写写进报告（用时 ${r.elapsed} 秒），正在签单……` })
        await refreshPreview()
        await refreshWb()
      }
      const r = await signPeriod(period, { known: known, note })
      setMsg({ ok: true, text: `已签单（状态 ${r.status}）。右侧即可下载这一版报告。` })
      onChanged()
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({
        ok: false,
        text: (h.status === 409 ? (h.body?.error ?? '服务端拒绝了这次签单') : (h.body?.error ?? h.message ?? '签单失败'))
          + (h.body?.hint ? `（${h.body.hint}）` : ''),
      })
    } finally { setBusy(null) }
  }

  async function doRevoke() {
    if (!period) return
    setBusy('revoke'); setMsg(null)
    try {
      const r = await revokePeriod(period, note)
      setMsg({ ok: true, text: `已撤回（状态 ${r.status}）` })
      onChanged()
    } catch (e) {
      const h = e as { body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '撤回失败' })
    } finally { setBusy(null) }
  }

  async function doFlag(loc: string) {
    if (!period) return
    try {
      await flagLoc(period, loc)
      await refreshWb()
    } catch (e) {
      const h = e as { body?: { error?: string }; message?: string }
      setMsg({ ok: false, text: h.body?.error ?? h.message ?? '标记失败' })
    }
  }

  function jumpTo(id: string) {
    const el = document.getElementById(`rv-ph-${id}`)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      ;(el as HTMLInputElement).focus({ preventScroll: true })
    }
  }

  function jumpNext() {
    if (emptyIds.length === 0) return
    jumpTo(emptyIds[cursor % emptyIds.length])
    setCursor((c) => (c + 1) % emptyIds.length)
  }

  function jumpToSign() {
    document.getElementById('rv-sign')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  if (!period) {
    return (
      <section className="card" style={{ padding: '22px 24px' }}>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="seal" size={22} />审核台
        </h2>
        <div className="pending-box" style={{ marginTop: 12 }}>先在顶栏选中一个期次。</div>
      </section>
    )
  }

  const back = `/app/?view=report&period=${encodeURIComponent(period)}`
  const signed = status === 'signed'
  const busyText = busy === 'sign' ? '正在处理…' : busy === 'rebuild' ? '正在重出……' :
    busy === 'save' ? '正在保存……' : busy === 'revoke' ? '正在撤回……' : ''

  return (
    <>
      <div className="rv-lead">
        <a className="hint" href={back} style={{ textDecoration: 'none' }}>← 回报告</a>
        <span style={{ color: 'var(--line)' }}>·</span>
        <span className="hint">期次 <b className="mono">{period}</b></span>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10, marginLeft: 4 }}>
          <Icon name="seal" size={22} />审核 · 试排报告
        </h2>
        <span className={`pill ${signed ? 'signed' : status === 'stale' ? 'stale' : 'unsigned'}`}>
          {signed ? '已签单' : status === 'stale' ? '签名已失效' : '未签单'}
        </span>
        {assertions && (
          <span className="hint">
            数据核对 {assertions.total - assertions.fail}/{assertions.total}
            {assertions.fail === 0 ? ' 全部通过' : `（${assertions.fail} 处对不上）`}
          </span>
        )}
        {preview && preview.docx && (
          <span className="hint">
            报告里的空 {nField} 处{nLeft > 0 ? `（还剩 ${nLeft} 处待填）` : '（已填齐）'}
          </span>
        )}
        {doubtN > 0 && <span className="hint" style={{ color: 'var(--gold-ink)', fontWeight: 650 }}>存疑 {doubtN} 处</span>}
      </div>

      {!isAdmin && (
        <div className="pending-box" style={{ marginTop: 12 }}>
          当前角色{me ? `（${me.role}）` : '未知'}是只读——签单与填写需要管理员权限。这是服务端的权限设置挡的。
        </div>
      )}

      {previewNote ? (
        <div className="pending-box" style={{ marginTop: 14 }}>
          {previewNote}
          {previewNote.includes('还没有出稿') && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
          {!previewNote.includes('权限') && (
            <> <button className="btn" style={{ padding: '4px 10px', fontSize: 13.5 }}
                     onClick={() => location.reload()}>重新读取</button></>
          )}
        </div>
      ) : !preview ? (
        <div className="pending-box" style={{ marginTop: 14 }}>正在读试排报告……</div>
      ) : (
        <div className="rv-grid">
          <section className="card rv-report" aria-label="试排报告全文">
            <p className="rv-docmeta">
              <span>本稿由流水线生成 · {preview.updated_at || '—'} · 数字全部来自台账；带虚线框的空请就地填写。</span>
              {emptyIds.length > 0 && (
                <button type="button" className="rv-next" onClick={jumpNext}>
                  还剩 {emptyIds.length} 处 · 跳到下一处 ↓
                </button>
              )}
            </p>
            {preview.blocks.map((b, i) => (
              <BlockView key={i} block={b} vals={vals} onVal={(id, v) => setVals((s) => ({ ...s, [id]: v }))}
                         disabled={!isAdmin || busy !== null} period={period} />
            ))}
          </section>

          <aside className="rv-side">
            {/* ------- 签单 ------- */}
            <section className="card rv-card" id="rv-sign">
              <h3><Icon name="seal" size={19} />审核 · 签单</h3>
              <div className="rv-kv"><span>报告版本</span><b className="rv-docname">{preview.docx ?? '—'}</b></div>
              <div className="rv-kv"><span>生成时间</span><b>{preview.updated_at || '—'}</b></div>
              <div className="rv-kv"><span>报告里的空</span><b>{nField} 处（待填 {nLeft}）</b></div>
              <div className="rv-kv"><span>存疑</span><b style={doubtN > 0 ? { color: 'var(--gold-ink)' } : undefined}>{doubtN} 处</b></div>
              <label className="rv-ack">
                <input type="checkbox" checked={known} disabled={!isAdmin || busy !== null}
                       onChange={(e) => setKnown(e.target.checked)} />
                <span>我已逐项看过<b>待人工 {nField} 处、存疑 {doubtN} 处</b>，同意放行。</span>
              </label>
              <textarea
                className="rv-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="批注（可选）：这一版为什么可以签单、还有哪些已知问题"
                rows={2}
                disabled={!isAdmin}
              />
              <div className="rv-btns">
                <button className="btn primary" onClick={doSign}
                        disabled={!isAdmin || busy !== null || signed || (needAck && !known)}
                        title={needAck && !known ? '先勾选上方「我已逐项看过」' : undefined}>
                  <Icon name="seal" size={19} />{busy === 'sign' ? '正在处理…' : '签单'}
                </button>
                <ConfirmButton className="btn" disabled={!isAdmin || busy !== null || !signed}
                               confirmText="确认撤回？签名会失效" onConfirm={doRevoke}>
                  <Icon name="refresh" size={18} />撤回
                </ConfirmButton>
              </div>
              {needAck && !known && !signed && isAdmin && (
                <p className="rv-ackhint" role="note">先勾选上方「我已逐项看过」，签单才可用。</p>
              )}
              {pendingN > 0 && (
                <p className="rv-warn" role="note">
                  {signed
                    ? `有 ${pendingN} 处填写还没写进报告——点下方「保存并重出报告」写入；重出后签名失效，需重新签单。`
                    : `有 ${pendingN} 处填写还没写进报告——点「签单」会先自动写进报告再签。`}
                </p>
              )}
              {busyText && <p className="rv-busy" role="status">{busyText}</p>}
              {msg && <p className={msg.ok ? 'rv-msg ok' : 'rv-msg bad'} role="status">{msg.text}</p>}
              <p className="hint" style={{ marginTop: 8 }}>
                签前想核改动：<a href={`/app/?view=reading&period=${encodeURIComponent(period)}`}>看本期全部改动（对勘本）→</a>
              </p>
            </section>

            {/* ------- 下载 ------- */}
            <section className="card rv-card">
              <h3><Icon name="doc" size={19} />报告文件</h3>
              {signed ? (
                <a className="btn primary rv-dl" href={`/api/periods/${encodeURIComponent(period)}/download/report`}>
                  <Icon name="doc" size={19} />下载报告（Word）
                </a>
              ) : (
                <button className="btn rv-dl" disabled>
                  <Icon name="doc" size={19} />下载报告（Word）
                </button>
              )}
              <p className="hint" style={{ marginTop: 8 }}>
                {signed ? '已签单，可下载。'
                  : status === 'stale' ? '签名已失效，重签后可下载。'
                    : '签单后可下载。'}
              </p>
            </section>

            {/* ------- 报告里的空 ------- */}
            <section className="card rv-card">
              <h3><Icon name="list" size={19} />报告里的空
                <span className="hint" style={{ fontWeight: 400, marginLeft: 'auto' }}>
                  {nLeft > 0 ? `还剩 ${nLeft} 处` : '已填齐'}{doubtN > 0 ? ` · 存疑 ${doubtN} 处` : ''}
                </span>
              </h3>
              {nField > 0 && (
                <button type="button" className="btn rv-nextbtn" onClick={jumpNext}
                        disabled={emptyIds.length === 0}
                        title="按报告顺序跳到下一处未填的空，并聚焦到输入框">
                  {emptyIds.length > 0 ? `跳到下一处未填（还剩 ${emptyIds.length} 处）` : '都已填齐'}
                </button>
              )}
              {nField > 0 && (
                <div className="rv-chips" role="group" aria-label="按存疑筛选">
                  <button type="button" className={`rv-chip${!onlyDoubt ? ' on' : ''}`}
                          onClick={() => setOnlyDoubt(false)}>全部 {nField}</button>
                  <button type="button" className={`rv-chip${onlyDoubt ? ' on' : ''}`}
                          onClick={() => setOnlyDoubt(true)} disabled={doubtN === 0}
                          title={doubtN === 0 ? '还没有标存疑的处' : '只看已标存疑的处'}>
                    只看存疑 {doubtN}
                  </button>
                </div>
              )}
              {nField === 0 ? (
                <p className="hint" style={{ marginTop: 8 }}>
                  这一期没有要人填的地方——可直接签单。
                  <button type="button" className="btn" style={{ marginLeft: 10, padding: '4px 12px', fontSize: 13 }}
                          onClick={jumpToSign}>去签单 ↓</button>
                </p>
              ) : fieldsShown.length === 0 ? (
                <p className="hint" style={{ marginTop: 8 }}>这一期还没有标存疑的处。</p>
              ) : (
                <ul className="rv-todo">
                  {fieldsShown.map(([id, meta]) => {
                    const v = vals[id] ?? ''
                    const isDoubt = !!doubt[meta.where]
                    return (
                      <li key={id}>
                        <button type="button" className="rv-jump" onClick={() => jumpTo(id)}>
                          <span className={`rv-dot${v.trim() ? ' done' : ''}`} aria-hidden="true" />
                          <span className="rv-todo-t">{meta.title}</span>
                          <span className="rv-todo-v">{v.trim() ? '已填' : '待填'}</span>
                        </button>
                        <button type="button" className={`rv-flag${isDoubt ? ' on' : ''}`}
                                title={isDoubt ? '取消存疑' : '这一处标存疑'}
                                onClick={() => doFlag(meta.where)} disabled={!isAdmin || busy !== null}>
                          {isDoubt ? '已存疑' : '存疑'}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
              {(wb?.todo_confirm ?? []).length > 0 && (
                <>
                  <p className="hint" style={{ marginTop: 10 }}>另需核一眼（不用填）：</p>
                  <ul className="rv-todo rv-confirm">
                    {wb!.todo_confirm.map((t) => (
                      <li key={t.id}><span className="rv-todo-t">{t.title}</span></li>
                    ))}
                  </ul>
                </>
              )}
              {wbNote && (
                <p className="hint" style={{ color: 'var(--bad)' }}>
                  {wbNote}
                  {!wbNote.includes('权限') && (
                    <button type="button" className="btn" style={{ marginLeft: 10, padding: '3px 10px', fontSize: 13 }}
                            onClick={() => { void refreshWb().catch(() => setWbNote('填写记录还是读不到——稍后再试。')) }}>
                      重新读取
                    </button>
                  )}
                </p>
              )}
              <div className="rv-btns" style={{ marginTop: 12 }}>
                <button className="btn" onClick={doSave}
                        disabled={!isAdmin || busy !== null || nField === 0}>
                  <Icon name="doc" size={18} />保存填写
                </button>
                <ConfirmButton className="btn primary rv-wide"
                               disabled={!isAdmin || busy !== null || nField === 0}
                               confirmText="确认重出？旧稿会先撤下、可回滚"
                               title="把填的值写进报告并重出（约 2–15 秒）"
                               onConfirm={doRebuild}>
                  <Icon name="refresh" size={18} />{busy === 'rebuild' ? '正在重出……' : '保存并重出报告'}
                </ConfirmButton>
              </div>
              <p className="hint" style={{ marginTop: 8 }}>
                填的值只进报告，台账一个字节不动{appliedN > 0 ? `；已写入 ${appliedN} 处` : ''}。
              </p>
            </section>
          </aside>
        </div>
      )}
    </>
  )
}
