/* 逐格溯源（阶段 1 · P1）——报告里的每个数字，**现场回台账重读一遍**对给你看。
   数据源 GET /api/periods/{p}/trace（后端已交付：分类 + 分页）。
   🔴 只透传后端给的行；不换算、不聚合、不四舍五入。 */

import { useCallback, useEffect, useState } from 'react'
import { req } from './api'
import { Icon } from './icons'
import { errorNote } from './lib/status'

type TraceRow = {
  loc: string; col?: string; report?: string; label?: string
  sheet?: string; src_ref?: string; ledger?: string; how?: string
}
type TraceData = {
  period: string; ledger?: string; ledger_ok?: boolean; n?: number
  cat?: string; counts?: Record<string, number>; rows?: TraceRow[]
  total?: number; limit?: number; offset?: number; has_more?: boolean
}
const CAT_LABEL: Record<string, string> = {
  bigtable: '大表', province: '省域表', matrix: '学科×高校矩阵', charts: '图表', texts: '正文与其他',
}
const PAGE = 60

export function Trace({ period }: { period: string | null }) {
  const [cat, setCat] = useState('')
  const [data, setData] = useState<TraceData | null>(null)
  const [rows, setRows] = useState<TraceRow[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (c: string, offset: number, append: boolean) => {
    if (!period) return
    setBusy(true)
    try {
      const j = await req<TraceData>(
        `/api/periods/${encodeURIComponent(period)}/trace?limit=${PAGE}&offset=${offset}${c ? `&cat=${encodeURIComponent(c)}` : ''}`,
      )
      setData(j)
      setRows((old) => (append ? [...old, ...(j.rows ?? [])] : (j.rows ?? [])))
      setNote(null)
    } catch (e) {
      setNote(errorNote(e, '溯源数据'))
    } finally { setBusy(false) }
  }, [period])

  useEffect(() => { setRows([]); setCat(''); setData(null); load('', 0, false) }, [period, load])

  function pick(c: string) { setCat(c); setRows([]); load(c, 0, false) }

  return (
    <section className="card mt-18 pad-card">
      <p className="hint mb-10">
        <a href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>← 回报告</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>
      <h2 className="h-sec">
        <Icon name="list" size={21} />逐格溯源
        {data?.n != null && <span className="hint hint-num">可溯源 {data.n} 处</span>}
        {data?.ledger_ok === false && (
          <span className="pill warn-border">台账不在本机，重读不可用</span>
        )}
      </h2>

      {note ? (
        <div className="pending-box mt-12">
          {note}
          {note.includes('可能尚未出稿') && period && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
        </div>
      ) : !data ? (
        <div className="pending-box mt-12">正在回台账重读……</div>
      ) : (
        <>
          <div className="chips mt-12">
            <button className={`switch${cat === '' ? ' on' : ''}`} type="button" onClick={() => pick('')}>
              全部 <b className="mono">{data.n ?? ''}</b>
            </button>
            {Object.entries(data.counts ?? {}).map(([k, v]) => (
              <button key={k} className={`switch${cat === k ? ' on' : ''}`} type="button" onClick={() => pick(k)}>
                {CAT_LABEL[k] ?? k} <b className="mono">{v}</b>
              </button>
            ))}
          </div>

          <div className="tablewrap mt-12">
            <table>
              <thead>
                <tr>
                  <th className="w-150">位置</th>
                  <th className="w-170">报告里</th>
                  <th className="w-190">台账现值</th>
                  <th className="w-210">来源</th>
                  <th>怎么来的</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.loc}-${i}`}>
                    <td className="mono fs-135 ink-3">
                      {r.loc}
                      {r.label && <><br /><span className="fs-125">{r.label}</span></>}
                    </td>
                    <td className="ink-zhu">{r.report}</td>
                    <td className="mono fs-135">{r.ledger ?? '（台账读不到）'}</td>
                    <td className="fs-135">{r.sheet}{r.src_ref ? <> · <span className="mono">{r.src_ref}</span></> : null}</td>
                    <td className="fs-135 ink-2">{r.how}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="rowc12 mt-12">
            <span className="hint">
              已铺 {rows.length} / {data.total ?? '—'} 行
            </span>
            {data.has_more && (
              <button className="btn" disabled={busy} onClick={() => load(cat, rows.length, true)}>
                <Icon name="refresh" size={19} />{busy ? '正在读……' : '再看下一批'}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
