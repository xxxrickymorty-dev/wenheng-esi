/* 图册（前端 ECharts 化，2026-10-28 rick 裁决）——本期报告写入的全部配图。
   数字来自 GET /api/periods/<p>/charts-data（src/chart_data.py 同源导出，
   与报告 PNG 同一批，前端不换算）；没有对应数据的图（老期次预测图、接口未就绪）
   如实回退 PNG 原图。与对勘本的分工不变：对勘槽位永远比对报告实况（PNG）。
   设计稿：web/mockups/图册-ECharts集成（静态稿 20261028）.html */

import { useEffect, useMemo, useState } from 'react'
import { getCharts, type ChartRow } from './api-collation'
import { chartDataFor, getChartsData, type ChartsData } from './lib/chartsData'
import { buildOption, chartTable } from './charts/build'
import { ChartFigure } from './charts/ChartFigure'
import { Icon } from './icons'
import { appHref, errorNote } from './lib/status'
import { chartGroupLabel } from './lib/labels'

function ChartCell({ row, data }: { row: ChartRow; data: ChartsData | null }) {
  const hit = useMemo(
    () => (data ? chartDataFor(data, row.group, row.name) : null),
    [data, row.group, row.name])
  const option = useMemo(() => (hit ? buildOption(hit) : null), [hit])
  const caption = row.label || row.name
  return (
    <figure className="gal-cell">
      {option
        ? <ChartFigure option={option} ariaLabel={caption} />
        : <a href={row.url} target="_blank" rel="noreferrer">
            <img className="gal-img" src={row.url} alt={caption} loading="lazy" decoding="async" />
          </a>}
      {hit ? chartTable(hit) : null}
      <figcaption className="gal-cap">
        <span>{caption}</span>
        <a href={row.url} target="_blank" rel="noreferrer"
           title="这张图的 PNG 原图（进报告的就是它）">PNG</a>
      </figcaption>
    </figure>
  )
}

export function Charts({ period }: { period: string | null }) {
  const [rows, setRows] = useState<ChartRow[] | null>(null)
  const [data, setData] = useState<ChartsData | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!period) return
    let alive = true
    setRows(null); setData(null); setNote(null); setQ('')
    // 图册清单与同源数据各取各的：数据缺席（老期次/接口未就绪）不拦清单
    getCharts(period)
      .then((r) => { if (alive) setRows(r) })
      .catch((e) => { if (alive) setNote(errorNote(e, '图册')) })
    getChartsData(period)
      .then((r) => { if (alive) setData(r) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [period])

  const shown = useMemo(() => {
    if (!rows) return []
    const k = q.trim().toLowerCase()
    return k ? rows.filter((r) => `${chartGroupLabel(r.group)} ${r.group} ${r.name}`.toLowerCase().includes(k)) : rows
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
    <section className="card mt-18 pad-card">
      <p className="hint mb-10">
        <a href={period ? appHref('report', period) : '/app/?view=report'}>← 回报告</a>
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
                <h3>{chartGroupLabel(g)}</h3>
                <span className="hint mono">{list.length} 张</span>
              </div>
              <div className="gal-echart">
                {list.map((c) => <ChartCell key={c.url} row={c} data={data} />)}
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
