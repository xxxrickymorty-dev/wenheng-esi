/* 图册全量（阶段 1 · P0-4）——本期报告写入的全部配图。
   设计稿：web/mockups/报告深入视图.html（视图四）· 数据源 GET /api/periods/{p}/charts
   与对勘本的分工：这里是「按图名找 / 脱离槽位单看图」的入口；槽位视图在报告屏的对勘里。 */

import { useEffect, useMemo, useState } from 'react'
import { getCharts, type ChartRow } from './api-collation'
import { Icon } from './icons'

export function Charts({ period }: { period: string | null }) {
  const [rows, setRows] = useState<ChartRow[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!period) return
    let alive = true
    setRows(null); setNote(null); setQ('')
    getCharts(period)
      .then((r) => { if (alive) setRows(r) })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setNote(
          e.status === 403 ? '图册需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有图册（可能尚未出稿）。'
              : '读图册失败。',
        )
      })
    return () => { alive = false }
  }, [period])

  const shown = useMemo(() => {
    if (!rows) return []
    const k = q.trim().toLowerCase()
    return k ? rows.filter((r) => `${r.group} ${r.name}`.toLowerCase().includes(k)) : rows
  }, [rows, q])

  const byGroup = useMemo(() => {
    const m = new Map<string, ChartRow[]>()
    for (const r of shown) {
      const g = r.group || '其他'
      if (!m.has(g)) m.set(g, [])
      m.get(g)!.push(r)
    }
    return [...m.entries()]
  }, [shown])

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <p className="hint mb-10">
        <a href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>← 回报告</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>
      <h2 className="h-sec">
        <Icon name="chart" size={21} />图表图册
        {rows && <span className="hint hint-num">共 {rows.length} 张</span>}
      </h2>

      {note ? (
        <div className="pending-box mt-12">
          {note}
          {note.includes('可能尚未出稿') && period && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
        </div>
      ) : !rows ? (
        <div className="pending-box mt-12">正在读图册……</div>
      ) : (
        <>
          <div className="toolbar mt-12">
            <input className="search" value={q} onChange={(e) => setQ(e.target.value)}
                   aria-label="搜索图名或学科" placeholder="搜索图名 / 学科…" />
            <span className="hint">匹配 <b className="mono">{shown.length} / {rows.length}</b> 张</span>
          </div>
          {byGroup.map(([g, list]) => (
            <div key={g}>
              <div className="sec-h">
                <h3>{g}</h3>
                <span className="hint mono">{list.length} 张</span>
              </div>
              <div className="gal">
                {list.map((c) => (
                  <a key={c.url} href={c.url} target="_blank" rel="noreferrer" title={`${g} / ${c.name}`}>
                    <img src={c.url} alt={c.name} loading="lazy"
                         style={{ width: '100%', border: '1px solid var(--line)',
                                  borderRadius: 'var(--r-sm)', background: 'var(--panel)' }} />
                    <span className="hint" style={{ fontSize: 13 }}>{c.name}</span>
                  </a>
                ))}
              </div>
            </div>
          ))}
          {shown.length === 0 && (
            <p className="hint mt-10">{q.trim() ? `没有匹配「${q}」的图。` : '这一期还没有图表。'}</p>
          )}
        </>
      )}
    </section>
  )
}
