/* 对勘本 · 正文级阅读（阶段 1 · P0-2）——「报告是主角」的那一屏。
   设计稿：web/mockups/报告深入视图.html（视图二）· 数据源 GET /api/periods/{p}/collation
   🔴 只透传后端给的行；「待人工」按后端 manual 标记筛，不自己判断。 */

import { useEffect, useMemo, useState } from 'react'
import { getCollation, type CollationRow } from './api-collation'
import { getFacts } from './api-workbench'
import { Icon } from './icons'
import { appHref, errorNote } from './lib/status'
import { collationSectionLabel } from './lib/labels'

const CAP = 120   // 单个分组最多渲染这么多条（大表组可能几百条）；其余提示走搜索

export function Reading({ period }: { period: string | null }) {
  const [rows, setRows] = useState<CollationRow[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [onlyManual, setOnlyManual] = useState(false)
  const [sec, setSec] = useState<string | null>(null)
  const [hover, setHover] = useState<CollationRow | null>(null)
  const [assertions, setAssertions] = useState<{ total: number; fail: number } | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setRows(null); setNote(null); setQ(''); setOnlyManual(false); setSec(null); setHover(null); setAssertions(null)
    /* 全量（716 处量级）：分组、搜索、待人工都在全量上做——
       后端默认分页 50 行，拿它当全量会只剩前几组。 */
    getCollation(period, true)
      .then((r) => { if (alive) setRows(r) })
      .catch((e) => {
        if (!alive) return
        setNote(errorNote(e, '对勘本', { n404: '这一期还没有对勘数据（可能尚未出稿）。' }))
      })
    getFacts(period).then((f) => { if (alive) setAssertions(f.assertions) }).catch(() => { /* 断言读数取不到就不显示，不编 */ })
    return () => { alive = false }
  }, [period])

  /* 分组：按后端给的 section，保持后端顺序 */
  const sections = useMemo(() => {
    const m = new Map<string, CollationRow[]>()
    for (const r of rows ?? []) {
      const k = r.section || '其他'
      if (!m.has(k)) m.set(k, [])
      m.get(k)!.push(r)
    }
    return [...m.entries()]
  }, [rows])

  useEffect(() => {
    if (!sections.length || sec) return
    /* 报告屏点某一组进来时带 ?section=，直接落那一组；否则第一组 */
    const want = new URLSearchParams(location.search).get('section')
    setSec(sections.some(([k]) => k === want) ? (want as string) : sections[0][0])
  }, [sections, sec])

  /* ← → 换分组 */
  useEffect(() => {
    if (!sections.length) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      const i = sections.findIndex(([k]) => k === sec)
      const j = e.key === 'ArrowLeft' ? i - 1 : i + 1
      if (j >= 0 && j < sections.length) { setSec(sections[j][0]); e.preventDefault() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sections, sec])

  const nManual = (rows ?? []).filter((r) => r.manual).length

  const shown = useMemo(() => {
    const inSec = (rows ?? []).filter((r) => (r.section || '其他') === sec)
    const k = q.trim().toLowerCase()
    return inSec.filter((r) => {
      if (onlyManual && !r.manual) return false
      if (!k) return true
      return `${r.loc} ${r.old} ${r.new} ${r.oldPreview ?? ''} ${r.newPreview ?? ''} ${r.source ?? ''}`.toLowerCase().includes(k)
    })
  }, [rows, sec, q, onlyManual])

  const back = period ? appHref('report', period) : '/app/?view=report'

  return (
    <>
      <p className="hint mb-10">
        <a href={back}>← 回报告</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>

      <section className="card pad-18-20-6">
        <h2 className="h-sec fs-20">
          <Icon name="doc" size={21} />对勘本 · 正文级对照
          <span className="hint hint-num">
            本期改动 <b className="mono">{rows?.length ?? 0}</b> 处
            {nManual > 0 && <> · 待人工 <b className="mono ink-zhu">{nManual}</b> 处</>}
          </span>
          {assertions && (
            <span className="pill ml-auto">
              数据校验 {assertions.total}/{assertions.total} {assertions.fail === 0 ? '全部通过' : `${assertions.fail} 处对不上`}
            </span>
          )}
        </h2>

      {note ? (
        <div className="pending-box block-12-16">
          {note}
          {note.includes('可能尚未出稿') && period && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
        </div>
        ) : !rows ? (
          <div className="pending-box block-12-16">正在读对勘数据……</div>
        ) : (
          <div className="toolbar pb-12">
            <input className="search" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="搜索位置 / 改动文字 / 来源…" />
            <button className={`switch${onlyManual ? ' on' : ''}`} type="button"
                    onClick={() => setOnlyManual((v) => !v)}
                    aria-pressed={onlyManual}>
              仅看待人工 <b className="mono">{nManual}</b>
            </button>
          </div>
        )}
      </section>

      {rows && sections.length > 0 && (
        <div className="card reading-grid mt-16">
          {/* 左：槽位分组 */}
          <nav className="col-l">
            <div className="hint mono rd-head">槽 位 分 组</div>
            {sections.map(([k, list]) => (
              <a key={k} className="nav-i" href="#" aria-current={k === sec}
                 onClick={(e) => { e.preventDefault(); setSec(k) }}>
                <span>{collationSectionLabel(k)}</span><span className="n">{list.length}</span>
              </a>
            ))}
            <div className="kv rd-sep">
              <span className="k">命中</span><span className="v">{shown.length}</span>
            </div>
          </nav>

          {/* 中：改动卡 */}
          <div className="col-m">
            <h3 className="baseline-row">
              {sec ? collationSectionLabel(sec) : ''}
              <span className="hint mono ml-auto">{shown.length} 处</span>
            </h3>
            <div className="mt-12">
              {shown.slice(0, CAP).map((r, i) => (
                <article key={`${r.loc}-${i}`} className="chg"
                         onMouseEnter={() => setHover(r)} onFocus={() => setHover(r)} tabIndex={0}>
                  <div className="chg-h">
                    <span className="loc">{r.loc}</span>
                    <span className={`pill${r.manual ? ' manual' : ''} pad-1-9`}>
                      {r.manual ? '待人工' : '已替换'}
                    </span>
                    {r.source && <span className="hint ml-auto fs-13">来源：{r.source}</span>}
                  </div>
                  <div className="chg-b">
                    <div className="row">
                      <span className="t">母版原文</span>
                      <span className="old">{r.oldPreview ?? r.old ?? '（此处为空）'}</span>
                    </div>
                    <div className="row">
                      <span className="t">本期</span>
                      <span className={r.manual ? 'new' : 'new'}>
                        {r.manual ? '（待你补：这一处没有权威来源）' : (r.newPreview ?? r.new ?? '（空）')}
                      </span>
                    </div>
                  </div>
                </article>
              ))}
              {shown.length > CAP && (
                <p className="hint">
                  另 {shown.length - CAP} 处见
                  <a href={`/app/?view=red${period ? `&period=${encodeURIComponent(period)}` : ''}`}> 红色件清单</a>。
                </p>
              )}
              {shown.length === 0 && <p className="hint">{onlyManual ? '本组无待人工。' : '本组无匹配改动。'}</p>}
            </div>
          </div>

          {/* 右：校记 */}
          <aside className="col-r">
            <h3 className="baseline">
              校 记 <span className="hint ml-auto">{period}</span>
            </h3>
            <div className="kv mt-10"><span className="k">本期改动</span><span className="v">{rows.length} 处</span></div>
            <div className="kv"><span className="k">槽位分组</span><span className="v">{sections.length} 组</span></div>
            <div className="kv"><span className="k">待人工</span><span className="v ink-zhu">{nManual} 处</span></div>
            {assertions && (
              <div className="kv"><span className="k">数据校验</span>
                <span className="v" style={{ color: assertions.fail === 0 ? 'var(--ok)' : 'var(--bad)' }}>
                  {assertions.total - assertions.fail} / {assertions.total} {assertions.fail === 0 ? '· 全部通过' : ''}
                </span></div>
            )}
            {hover ? (
              <div className="pop">
                <div className="ph">出处</div>
                <div className="pc">{hover.source || '（后端未给来源）'}</div>
                <div className="ph mt-6">位置</div>
                <div className="pc">{hover.loc}</div>
                <div className="ph mt-6">改动</div>
                <div className="pc fw-400">
                  {(hover.oldPreview ?? hover.old ?? '（空）')} → {(hover.manual ? '待人工补录' : (hover.newPreview ?? hover.new ?? '（空）'))}
                </div>
              </div>
            ) : null}
            <p className="hint mt-12">
              签单去<a href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}>审核台</a>。
            </p>
          </aside>
        </div>
      )}
    </>
  )
}
