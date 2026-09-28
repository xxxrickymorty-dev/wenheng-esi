/* 对勘本 · 正文级阅读（阶段 1 · P0-2）——「报告是主角」的那一屏。
   设计稿：web/mockups/报告深入视图.html（视图二）· 数据源 GET /api/periods/{p}/collation
   🔴 只透传后端给的行；「待人工」按后端 manual 标记筛，不自己判断。 */

import { useEffect, useMemo, useState } from 'react'
import { getCollation, type CollationRow } from './api2'
import { getFacts } from './api4'
import { Icon } from './icons'

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
      .catch((e: { status?: number }) => {
        if (!alive) return
        setNote(
          e.status === 403 ? '对勘本需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有对勘数据（可能尚未出稿）。'
              : '读对勘数据失败。',
        )
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

  const back = `/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`

  return (
    <>
      <p className="hint" style={{ marginBottom: 10 }}>
        <a href={back}>← 回报告</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>

      <section className="card" style={{ padding: '18px 20px 6px' }}>
        <h2 style={{ fontSize: 20, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Icon name="doc" size={21} />对勘本 · 正文级对照
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            本期改动 <b className="mono">{rows?.length ?? 0}</b> 处
            {nManual > 0 && <> · 待人工 <b className="mono" style={{ color: 'var(--zhu)' }}>{nManual}</b> 处</>}
          </span>
          {assertions && (
            <span className="pill" style={{ marginLeft: 'auto' }}>
              机器断言 {assertions.total}/{assertions.total} {assertions.fail === 0 ? '全绿' : `有 ${assertions.fail} 项不符`}
            </span>
          )}
        </h2>

      {note ? (
        <div className="pending-box" style={{ margin: '12px 0 16px' }}>
          {note}
          {note.includes('可能尚未出稿') && period && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
        </div>
        ) : !rows ? (
          <div className="pending-box" style={{ margin: '12px 0 16px' }}>正在读对勘数据……</div>
        ) : (
          <div className="toolbar" style={{ paddingBottom: 12 }}>
            <input className="search" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="搜索位置 / 改动文字 / 来源…" />
            <button className={`switch${onlyManual ? ' on' : ''}`} type="button"
                    onClick={() => setOnlyManual((v) => !v)}
                    aria-pressed={onlyManual}>
              仅看待人工 <b className="mono">{nManual}</b>
            </button>
            <span className="hint">把光标移到改动卡上看台账出处 · 按 <b className="mono">← →</b> 换分组</span>
          </div>
        )}
      </section>

      {rows && sections.length > 0 && (
        <div className="card reading-grid" style={{ marginTop: 16 }}>
          {/* 左：槽位分组 */}
          <nav className="col-l">
            <div className="hint mono" style={{ padding: '0 18px 8px', letterSpacing: '.2em' }}>槽 位 分 组</div>
            {sections.map(([k, list]) => (
              <a key={k} className="nav-i" href="#" aria-current={k === sec}
                 onClick={(e) => { e.preventDefault(); setSec(k) }}>
                <span>{k}</span><span className="n">{list.length}</span>
              </a>
            ))}
            <div className="kv" style={{ margin: '12px 18px 0', borderTop: '1px solid var(--line)', paddingTop: 10 }}>
              <span className="k">命中</span><span className="v">{shown.length}</span>
            </div>
          </nav>

          {/* 中：改动卡 */}
          <div className="col-m">
            <h3 style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              {sec}
              <span className="hint mono" style={{ marginLeft: 'auto' }}>{shown.length} 处</span>
            </h3>
            <div style={{ marginTop: 12 }}>
              {shown.slice(0, CAP).map((r, i) => (
                <article key={`${r.loc}-${i}`} className="chg"
                         onMouseEnter={() => setHover(r)} onFocus={() => setHover(r)} tabIndex={0}>
                  <div className="chg-h">
                    <span className="loc">{r.loc}</span>
                    <span className={`pill${r.manual ? ' manual' : ''}`} style={{ padding: '1px 9px' }}>
                      {r.manual ? '待人工' : '已替换'}
                    </span>
                    {r.source && <span className="hint" style={{ marginLeft: 'auto', fontSize: 13 }}>来源：{r.source}</span>}
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
                  还有 {shown.length - CAP} 处没铺开（这一组太大）——用上面的搜索定位，或到
                  <a href={`/app/?view=red${period ? `&period=${encodeURIComponent(period)}` : ''}`}> 红件清单 </a>看全量。
                </p>
              )}
              {shown.length === 0 && <p className="hint">{onlyManual ? '这一组没有待人工的地方。' : '这一组没有匹配的改动。'}</p>}
            </div>
          </div>

          {/* 右：校记 */}
          <aside className="col-r">
            <h3 style={{ display: 'flex', alignItems: 'baseline' }}>
              校 记 <span className="hint" style={{ marginLeft: 'auto' }}>{period}</span>
            </h3>
            <div className="kv" style={{ marginTop: 10 }}><span className="k">本期改动</span><span className="v">{rows.length} 处</span></div>
            <div className="kv"><span className="k">槽位分组</span><span className="v">{sections.length} 组</span></div>
            <div className="kv"><span className="k">待人工</span><span className="v" style={{ color: 'var(--zhu)' }}>{nManual} 处</span></div>
            {assertions && (
              <div className="kv"><span className="k">机器断言</span>
                <span className="v" style={{ color: assertions.fail === 0 ? 'var(--ok)' : 'var(--bad)' }}>
                  {assertions.total - assertions.fail} / {assertions.total} {assertions.fail === 0 ? '· 全绿' : ''}
                </span></div>
            )}
            <p className="hint" style={{ marginTop: 10 }}>把光标移到左侧任意一条改动上，这里显示它的出处。</p>
            {hover ? (
              <div className="pop">
                <div className="ph">出处</div>
                <div className="pc">{hover.source || '（后端未给来源）'}</div>
                <div className="ph" style={{ marginTop: 6 }}>位置</div>
                <div className="pc">{hover.loc}</div>
                <div className="ph" style={{ marginTop: 6 }}>改动</div>
                <div className="pc" style={{ fontWeight: 400 }}>
                  {(hover.oldPreview ?? hover.old ?? '（空）')} → {(hover.manual ? '待人工补录' : (hover.newPreview ?? hover.new ?? '（空）'))}
                </div>
              </div>
            ) : (
              <div className="pop" style={{ opacity: .55 }}>
                <div className="ph">出处</div>
                <div className="pc">（把光标移到左侧改动卡上）</div>
              </div>
            )}
            <p className="hint" style={{ marginTop: 12 }}>
              签单走<a href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}>审核台</a>——两道闸在那边，这一屏只读。
            </p>
          </aside>
        </div>
      )}
    </>
  )
}
