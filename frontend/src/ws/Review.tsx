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
import { flagLoc, revokePeriod, signPeriod } from './api-sign'
import { getWorkbench, postFill, type WorkbenchData } from './api-workbench'
import {
  getReportPreview, rebuildPeriod, reportImageUrl,
  type PreviewBlock, type PreviewSeg, type ReportPreview,
} from './api-report'
import { ConfirmButton } from './ConfirmButton'
import { FactsStrip } from './Report'
import { Icon } from './icons'

import { appHref, errorNote } from './lib/status'

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
    /* 图占位（2026-10-16）：按 docx 原尺寸同时锁定宽与比例——懒加载图落位不再撑版面，
       否则「报告里的空」深跳转会被中途加载的图顶走（rick 实测落在上一节）。 */
    const style: CSSProperties | undefined = block.w_cm
      ? {
        width: `${Math.round(block.w_cm * 37.8)}px`,
        ...(block.h_cm ? { aspectRatio: `${block.w_cm} / ${block.h_cm}` } : {}),
      }
      : undefined
    return (
      <p className="rv-img">
        <img src={reportImageUrl(period, block.rid)} alt="报告插图" loading="lazy" decoding="async"
             style={style} />
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
                  {(cell.imgs ?? []).map((im) => (
                    <img key={im.rid} src={reportImageUrl(period, im.rid)} alt="图表"
                         loading="lazy" decoding="async"
                         style={im.w_cm
                           ? {
                             width: `${Math.round(im.w_cm * 37.8)}px`,
                             ...(im.h_cm ? { aspectRatio: `${im.w_cm} / ${im.h_cm}` } : {}),
                           }
                           : undefined} />
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
  /* 浮动工具签（报告里的空）与批注折叠的开关 */
  const [todoOpen, setTodoOpen] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const isAdmin = me?.capabilities?.actions?.edit ?? me?.role === 'admin'
  /* 2026-10-12：审批（签单/撤回）对操作员也开放；在线填、标存疑、重出仍只管理员。 */
  const canSign = !!me

  useEffect(() => {
    if (!period) return
    let alive = true
    setPreview(null); setPreviewNote(null); setWb(null); setWbNote(null)
    setVals({}); setMsg(null); setKnown(false); setNote(''); setOnlyDoubt(false)

    getReportPreview(period)
      .then((pv) => { if (alive) setPreview(pv) })
      .catch((e) => {
        if (!alive) return
        setPreviewNote(errorNote(e, '审核台', { n404: '这一期还没有出稿。' }))
      })
    getWorkbench(period)
      .then((w) => {
        if (!alive) return
        setWb(w)
        const v: Record<string, string> = {}
        for (const t of w.todo_fill) if (t.filled?.trim()) v[t.id] = t.filled
        setVals(v)
      })
      .catch((e) => {
        if (!alive) return
        setWbNote(errorNote(e, '填写数据'))
      })
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
  /* 章节导航（2026-10-20）：报告 124 块、5 万余像素；抽「一 概述 / 二 …」做吸顶目录。 */
  const sections = useMemo(() => {
    const out: { i: number; title: string }[] = []
    for (const [i, b] of (preview?.blocks ?? []).entries()) {
      if (b.t !== 'p') continue
      const text = b.runs.map((r) => ('t' in r ? r.t : '')).join('').trim()
      if (/^[一二三四五六七八九十]+[\s、]/.test(text) && text.length <= 30) {
        out.push({ i, title: text })
      }
    }
    return out
  }, [preview])
  const headingAt = (i: number) => sections.find((s) => s.i === i)

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
  /* 本地还没保存的改动数——签单前那句统一文案要说清「点签单会先写进报告多少处」 */
  const changedN = useMemo(() => {
    const saved: Record<string, string> = {}
    if (wb) for (const t of wb.todo_fill) saved[t.id] = (t.filled ?? '').trim()
    let n = 0
    for (const [k, v] of Object.entries(vals)) if (v.trim() !== (saved[k] ?? '')) n++
    return n
  }, [wb, vals])
  /* 点「签单」会先写进报告的数量：服务端待应用 + 本地还没保存的改动 */
  const writeN = pendingN + changedN
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
      const h = e as { body?: { hint?: string } }
      setMsg({
        ok: false,
        text: errorNote(e, '签单', { n409: '服务端拒绝了这次签单' })
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
    if (!el) return
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    ;(el as HTMLInputElement).focus({ preventScroll: true })
    /* 懒加载图在滚动途中落位曾把目标顶走（2026-10-16 rick 实测「点击落在上一节」）：
       图已按原尺寸预留占位，这里再补两次校正兜底——只有目标完全不在视口里才补跳。 */
    const settle = () => {
      const r = el.getBoundingClientRect()
      if (r.bottom < 0 || r.top > window.innerHeight) {
        el.scrollIntoView({ block: 'center', behavior: 'auto' })
      }
    }
    window.setTimeout(settle, 700)
    window.setTimeout(settle, 1600)
  }

  function jumpNext() {
    if (emptyIds.length === 0) return
    jumpTo(emptyIds[cursor % emptyIds.length])
    setCursor((c) => (c + 1) % emptyIds.length)
  }

  if (!period) {
    return (
      <section className="card pad-card-lg">
        <h2 className="h-sec h-lg">
          <Icon name="seal" size={22} />审核台
        </h2>
        <div className="pending-box mt-12">先在顶栏选中一个期次。</div>
      </section>
    )
  }

  const back = appHref('report', period)
  const signed = status === 'signed'
  const busyText = busy === 'sign' ? '正在处理…' : busy === 'rebuild' ? '正在重出……' :
    busy === 'save' ? '正在保存……' : busy === 'revoke' ? '正在撤回……' : ''

  return (
    <>
      <div className="rv-lead">
        <a className="hint no-underline" href={back} >← 回报告</a>
        <span className="ink-line">·</span>
        <h2 className="h-sec h-lg ml-4">
          <Icon name="seal" size={22} />核验定稿
        </h2>
        {doubtN > 0 && <span className="hint gold-650">存疑 {doubtN} 处</span>}
      </div>

      {!isAdmin && (
        <div className="pending-box mt-12">
          操作员可以签单与撤回（审批）；在线填写、标存疑与重出报告仍仅管理员可用（服务端权限设置挡着）。
        </div>
      )}

      {previewNote ? (
        <div className="pending-box mt-14 rv-pending">
          {previewNote}
          {previewNote.includes('还没有出稿') && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
          {!previewNote.includes('权限') && (
            <> <button className="btn btn-xs" 
                     onClick={() => location.reload()}>重新读取</button></>
          )}
        </div>
      ) : !preview ? (
        <div className="pending-box mt-14">正在读试排报告……</div>
      ) : (
        /* 核验定稿 · 阅读流（2026-10-28 rick 裁「右侧签单栏去掉，报告太窄」）：
           单栏阅读——稿面限宽居中；签单收进吸底定稿条（已裁决口径：
           文末定稿条＋印章唯一状态表达＋两段式确认）；
           「报告里的空」收成右下浮动工具签，读稿时让位、要用一击展开。 */
        <div className="rv-flow">
          <FactsStrip period={period} />
          <section className="card rv-report" aria-label="试排报告全文">
            <p className="rv-docmeta">
              <span>本稿由流水线生成 · {preview.updated_at || '—'} · 数字全部来自台账；带虚线框的空请就地填写。</span>
              {emptyIds.length > 0 && (
                <button type="button" className="rv-next" onClick={jumpNext}>
                  还剩 {emptyIds.length} 处 · 跳到下一处 ↓
                </button>
              )}
            </p>
            {preview.blocks.map((b, i) => headingAt(i) ? (
              <div id={`rv-b-${i}`} key={i}>
                <BlockView block={b} vals={vals} onVal={(id, v) => setVals((s) => ({ ...s, [id]: v }))}
                           disabled={!isAdmin || busy !== null} period={period} />
              </div>
            ) : (
              <BlockView key={i} block={b} vals={vals} onVal={(id, v) => setVals((s) => ({ ...s, [id]: v }))}
                         disabled={!isAdmin || busy !== null} period={period} />
            ))}
          </section>

          {/* ------- 报告里的空：右下浮动工具签（读稿时让位） ------- */}
          {nField > 0 && (
            <div className="rv-floatdock">
              <div className="rv-todowrap">
              <button type="button" className="rv-todofab"
                      aria-expanded={todoOpen}
                      aria-label={`报告里的空：待填 ${nLeft} 处${doubtN > 0 ? `，存疑 ${doubtN} 处` : ''}`}
                      onClick={() => setTodoOpen((o) => !o)}>
                空 <b>{nLeft}</b>/{nField}{doubtN > 0 ? <i> · 疑 {doubtN}</i> : null}
              </button>
              {todoOpen && (
                <aside className="card rv-todopanel">
                  <div className="rv-todopanel-h">
                    <h3><Icon name="list" size={19} />报告里的空</h3>
                    <button type="button" className="rv-todopanel-x" aria-label="收起"
                            onClick={() => setTodoOpen(false)}>✕</button>
                  </div>
                  <button type="button" className="btn rv-nextbtn" onClick={jumpNext}
                          disabled={emptyIds.length === 0}
                          title="按报告顺序跳到下一处未填的空，并聚焦到输入框">
                    {emptyIds.length > 0 ? `跳到下一处未填（还剩 ${emptyIds.length} 处）` : '都已填齐'}
                  </button>
                  <div className="rv-chips" role="group" aria-label="按存疑筛选">
                    <button type="button" className={`rv-chip${!onlyDoubt ? ' on' : ''}`}
                            onClick={() => setOnlyDoubt(false)}>全部 {nField}</button>
                    <button type="button" className={`rv-chip${onlyDoubt ? ' on' : ''}`}
                            onClick={() => setOnlyDoubt(true)} disabled={doubtN === 0}
                            title={doubtN === 0 ? '还没有标存疑的处' : '只看已标存疑的处'}>
                      只看存疑 {doubtN}
                    </button>
                  </div>
                  {fieldsShown.length === 0 ? (
                    <p className="hint mt-8">没有标存疑的处。</p>
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
                      <p className="hint mt-10">另需核对：</p>
                      <ul className="rv-todo rv-confirm">
                        {wb!.todo_confirm.map((t) => (
                          <li key={t.id}><span className="rv-todo-t">{t.title}</span></li>
                        ))}
                      </ul>
                    </>
                  )}
                  {wbNote && (
                    <p className="hint ink-bad">
                      {wbNote}
                      {!wbNote.includes('权限') && (
                        <button type="button" className="btn ml-10 pad-3-10 fs-13"
                                onClick={() => { void refreshWb().catch(() => setWbNote('填写记录还是读不到——稍后再试。')) }}>
                          重新读取
                        </button>
                      )}
                    </p>
                  )}
                  <div className="rv-btns mt-12">
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
                  <p className="hint mt-8">
                    填的值只进报告、不动台账{appliedN > 0 ? `；已写入 ${appliedN} 处` : ''}。
                  </p>
                </aside>
              )}
            </div>
          </div>
          )}

          {/* ------- 定稿签：审核与签单的唯一收口（右侧悬浮） -------
              2026-10-28 二改（rick）：条上印章撤——左栏钤印是
              唯一状态表达；剩余内容收成右侧竖签悬浮，
              纸签压纸面，读稿不占版心。两段式确认原样。 */}
          <aside className="rv-sidesign" id="rv-sign" aria-label="审核与签单">
            {(busyText || msg) && (
              <p className={msg ? (msg.ok ? 'rv-msg ok' : 'rv-msg bad') : 'rv-busy'} role="status">
                {busyText || msg!.text}
              </p>
            )}
            <b className="rv-docname">{preview.docx ?? '—'}</b>
            <span className="rv-signmeta">
              生成 {preview.updated_at || '—'}<br />
              存疑 {doubtN} 处
              {nField > 0 ? ` · 待人工 ${nField} 处（已填 ${nField - nLeft}）` : ''}
            </span>
            {signed && (
              <span className="rv-signedline">
                已签单{me?.name ? ` · ${me.name}` : ''}，这一版已定稿
              </span>
            )}
            {!signed && status === 'stale' && (
              <span className="rv-signedline warn">签发已失效，重签后可下载</span>
            )}
            {needAck && !signed && (
              <div className="rv-confirm">
                <label className="rv-ack">
                  <input type="checkbox" checked={known} disabled={!canSign || busy !== null}
                         onChange={(e) => setKnown(e.target.checked)} />
                  <span>我已逐项看过待人工与存疑，同意放行。</span>
                </label>
                {noteOpen ? (
                  <textarea
                    className="rv-note"
                    aria-label="签单批注（可选）"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="批注（可选）：这一版为什么可以签单、还有哪些已知问题"
                    rows={2}
                    disabled={!canSign}
                    autoFocus
                  />
                ) : (
                  <button type="button" className="rv-notetoggle"
                          onClick={() => setNoteOpen(true)} disabled={!canSign}>
                    批注（可选）▾
                  </button>
                )}
                {nField > 0 && (
                  <p className="rv-warn" role="note">
                    {writeN > 0
                      ? `点「签单」会先把已填的 ${writeN} 处写进报告，再签发。`
                      : nLeft > 0
                        ? `还有 ${nLeft} 处待填，补齐后可点「签单」签发。`
                        : '点「签单」即可签发。'}
                  </p>
                )}
                {signed && writeN > 0 && (
                  <p className="rv-warn" role="note">
                    有 {writeN} 处填写还没写进报告——保存并重出后签发失效，需重新签单。
                  </p>
                )}
              </div>
            )}
            <div className="rv-signbtns">
              {signed ? (
                <a className="btn primary" href={`/api/periods/${encodeURIComponent(period)}/download/report`}>
                  <Icon name="doc" size={19} />下载报告（Word）
                </a>
              ) : (
                <button className="btn primary" onClick={doSign}
                        disabled={!canSign || busy !== null || signed || (needAck && !known)}
                        title={needAck && !known ? '先勾选「我已逐项看过」' : undefined}>
                  <Icon name="seal" size={19} />{busy === 'sign' ? '正在处理…' : '签单'}
                </button>
              )}
              <ConfirmButton className="btn ghost" disabled={!canSign || busy !== null || !signed}
                             confirmText="确认撤回？签发会失效" onConfirm={doRevoke}>
                <Icon name="refresh" size={18} />撤回
              </ConfirmButton>
              <a className="btn ghost" href={appHref('reading', period)}>看对勘本 →</a>
            </div>
          </aside>
        </div>
      )}
    </>
  )
}
