/* 他校简报（阶段 3 渲染层）：多校六期折线 + 事件标注 + 共同与差异表。
   数字全部来自 GET /api/periods/<期次>/panel-data（`flexible.panel()` 同源），
   事件标注来自后端 `events`——这一页不算数、不拼事件、不换颜色体系（全站单绿）。

   地址：/app/panel/?schools=昆明理工大学,海南大学,云南大学[&period=202609][&n=6] */

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ChartFigure } from './charts/ChartFigure'
import { schoolTrendOption, type ChartMarker } from './charts/options'
import { getPanelData, type PanelData } from './lib/panelData'
import { disciplineCn } from './lib/labels'
import { errorNote } from './lib/status'

/** 没带 ?schools= 时的默认对照（决赛演示用这三所：省内头部 + 省外对标） */
const DEFAULT_SCHOOLS = '昆明理工大学,海南大学,云南大学'

function readQuery() {
  const q = new URLSearchParams(window.location.search)
  return {
    schools: (q.get('schools') || DEFAULT_SCHOOLS).trim(),
    period: (q.get('period') || 'latest').trim(),
    n: Number(q.get('n')) || 6,
  }
}

export function Panel() {
  const [query, setQuery] = useState(readQuery)
  const [draft, setDraft] = useState(query.schools)
  const [data, setData] = useState<PanelData | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setData(null)
    setNote(null)
    getPanelData(query)
      .then((d) => { if (alive) setData(d) })
      .catch((e) => { if (alive) setNote(errorNote(e, '多校简报')) })
    return () => { alive = false }
  }, [query])

  /* 事件 → 图上标注：只换字段名，文字与下标都是后端给的 */
  const markers = useMemo<ChartMarker[]>(
    () => (data?.events ?? []).map((e) => ({
      index: e.index, text: e.text, kind: e.kind, school: e.school,
    })),
    [data])

  const option = useMemo(
    () => (data
      ? schoolTrendOption({
          periods: data.periods,
          schools: data.schools.map((s) => ({ name: s.cn, counts: s.counts })),
        }, markers)
      : null),
    [data, markers])

  function apply(event: FormEvent) {
    event.preventDefault()
    const next = { ...query, schools: draft.trim() || DEFAULT_SCHOOLS }
    setQuery(next)
    const url = new URL(window.location.href)
    url.searchParams.set('schools', next.schools)
    window.history.replaceState(null, '', url.pathname + url.search)
  }

  return (
    <div className="app-shell">
      <header className="app-top">
        <a className="app-brand" href="/app/">
          <b>文衡</b>
          <span>云南大学图书馆 · 学科信息参考</span>
        </a>
        <nav className="app-nav" aria-label="工作区">
          <a href="/app/">出报告</a>
          <a href="/app/panel/" aria-current="page">他校简报</a>
        </nav>
      </header>

      <main className="wrap">
        <section className="card pad-card">
          <h2 className="h-sec">
            他校简报
            {data && (
              <span className="hint hint-num">
                {data.periods[0]}–{data.periods[data.periods.length - 1]}
              </span>
            )}
          </h2>

          <form className="toolbar" onSubmit={apply}>
            <input className="search" value={draft} onChange={(e) => setDraft(e.target.value)}
                   aria-label="要对比的高校（逗号分隔）" placeholder="高校名，逗号分隔…" />
            <button className="btn" type="submit">看这几所</button>
          </form>

          {note ? (
            <div className="pending-box mt-12">{note}</div>
          ) : !data || !option ? (
            <div className="pending-box mt-12">正在读多校数据……首次约需二十秒</div>
          ) : (
            <ChartFigure option={option} height={360} ariaLabel="多校 ESI 上榜学科数趋势" />
          )}
        </section>

        {data && (
          <>
            <section className="card pad-card mt-18">
              <h2 className="h-sec">
                共同与差异
                <span className="hint hint-num">
                  共同学科 {data.summary.common_count} 个
                </span>
              </h2>
              <p className="hint mt-8" title={data.common.map(disciplineCn).join('、')}>
                {data.common.length ? data.common.map(disciplineCn).join('、') : '末期没有三校共有的学科。'}
              </p>
              <table className="mini-table mt-12">
                <thead>
                  <tr>
                    <th>学校</th>
                    {data.periods.map((p) => <th key={p}>{p}</th>)}
                    <th>本校另有</th>
                  </tr>
                </thead>
                <tbody>
                  {data.schools.map((s) => (
                    <tr key={s.cn}>
                      <td title={s.note || undefined}>{s.cn}</td>
                      {s.counts.map((v, i) => <td key={data.periods[i]}>{v == null ? '—' : v}</td>)}
                      <td>
                        {(data.only[s.cn] ?? []).map(disciplineCn).join('、') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="card pad-card mt-18">
              <h2 className="h-sec">
                事件
                <span className="hint hint-num">{data.events.length} 条</span>
              </h2>
              {data.events.length ? (
                <table className="mini-table mt-12">
                  <thead>
                    <tr><th>期次</th><th>学校</th><th>事件</th><th>学科数</th></tr>
                  </thead>
                  <tbody>
                    {data.events.map((e, i) => (
                      <tr key={`${e.school}-${e.period}-${e.kind}-${i}`}>
                        <td>{e.period}</td>
                        <td>{e.school}</td>
                        <td>{e.text}</td>
                        <td>{e.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="hint mt-10">
                  {data.missing.length
                    ? `窗口内缺数据：${data.missing.join('、')}，不出事件。`
                    : '这一窗口没有需要标注的变化。'}
                </p>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
