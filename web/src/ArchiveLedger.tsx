/* 运行档案 · 总账（2026-11-02 静态稿「运行档案」落 React）
   全部期次的每一次运行，一期一组：期次 / 签发 / 产物 三列按组跨行，状态与时间一次一行。
   点任一行进那一期的详情（`?view=archive&one=<期次>`）——总账本身只读，不聚合、不换算。
   词表一律取 lib/status（taskLabel / approvalLabel），页面不另写一份。 */

import { useEffect, useMemo, useState } from 'react'
import { getArchiveLedger, type ArchiveLedgerRow } from './api'
import { approvalLabel, errorNote, taskLabel } from './lib/status'
import './archive-ledger.css'

/** 状态 → 标记形状（色之外再看形）：实心方＝成、菱形＝提醒、斜方＝败、空心＝在跑／无记录 */
const ST_CLS: Record<string, string> = {
  completed: 'ok', warned: 'warn', failed: 'fail', cancelled: 'fail',
  escalated: 'fail', stalled: 'fail',
}

/** 这一库没有它的任务记录、但成品在（签过单）的期次：如实写「无运行记录」，不留空 */
function stOf(r: ArchiveLedgerRow): { cls: string; text: string } {
  if (!r.status) return { cls: 'none', text: '无运行记录' }
  return { cls: ST_CLS[r.status] ?? 'run', text: taskLabel(r.status) }
}

/** 时间只做截断（2026-10-24T08:01:12 → 10-24 08:01），不改口径 */
function shortAt(at: string): string {
  const s = at.replace('T', ' ')
  return s.length >= 16 ? s.slice(5, 16) : s || '—'
}

type Group = { period: string; approval: string; signedAt: string; rows: ArchiveLedgerRow[] }

export function ArchiveLedger({ onOpen }: { onOpen: (period: string) => void }) {
  const [rows, setRows] = useState<ArchiveLedgerRow[] | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    let alive = true
    getArchiveLedger()
      .then((d) => { if (alive) { setRows(d.rows); setNote('') } })
      .catch((e) => { if (alive) { setRows([]); setNote(errorNote(e, '运行档案')) } })
    return () => { alive = false }
  }, [])

  /* 任务记录新→旧，这里只按出现顺序分组（不重排——顺序本身是事实） */
  const groups = useMemo<Group[]>(() => {
    const out: Group[] = []
    for (const r of rows ?? []) {
      const last = out[out.length - 1]
      if (last && last.period === r.period) last.rows.push(r)
      else out.push({ period: r.period || '—', approval: r.approval, signedAt: r.signed_at, rows: [r] })
    }
    return out
  }, [rows])

  const warn = (rows ?? []).filter((r) => r.status === 'warned').length
  const fail = (rows ?? []).filter((r) => ST_CLS[r.status] === 'fail').length

  return (
    <>
      <header className="al-mast">
        <h1>运行档案</h1>
        <div className="al-figs">
          <div className="al-fig"><span>期</span><b>{groups.length || '—'}</b></div>
          <div className="al-fig"><span>运行</span><b>{rows ? rows.length : '—'}</b></div>
        </div>
      </header>

      <div className="al-rule" aria-hidden="true" />

      {note && <p className="al-note">{note}</p>}

      {rows == null ? null : rows.length === 0 ? (
        <p className="al-empty">还没有运行记录。</p>
      ) : (
        <>
          {(warn > 0 || fail > 0) && (
            <p className="al-hint">{[fail ? `${fail} 次失败` : '', warn ? `${warn} 次提醒` : ''].filter(Boolean).join('、')}</p>
          )}
          <div className="al-tw">
            <table className="al-led">
              <colgroup>
                <col style={{ width: '110px' }} /><col style={{ width: '190px' }} />
                <col style={{ width: '160px' }} /><col style={{ width: '130px' }} /><col />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">期次</th><th scope="col">状态</th><th scope="col">签发</th>
                  <th scope="col">时间</th><th scope="col">产物</th>
                </tr>
              </thead>
              {groups.map((g) => (
                <tbody key={g.period}>
                  {g.rows.map((r, i) => (
                    <tr key={r.id || `${g.period}-${i}`} className={i === 0 ? 'gstart' : undefined}>
                      {i === 0 && (
                        <th className="per" scope="rowgroup" rowSpan={g.rows.length}>
                          <button type="button" onClick={() => onOpen(g.period)}>{g.period}</button>
                        </th>
                      )}
                      <td className={`stc r-${stOf(r).cls}`}>
                        <span className="st"><i className={`mk mk-${stOf(r).cls}`} aria-hidden="true" />{stOf(r).text}</span>
                      </td>
                      {i === 0 && (
                        <td className="signc" rowSpan={g.rows.length}>
                          <span className={`sg ${g.approval}`}>
                            {g.approval === 'signed' && <i className="sk" aria-hidden="true">签</i>}
                            {approvalLabel(g.approval)}
                          </span>
                          {g.signedAt && <span className="sd">{g.signedAt.slice(0, 10)}</span>}
                        </td>
                      )}
                      <td className="ts">{shortAt(r.at)}</td>
                      {i === 0 && <td className="artc" rowSpan={g.rows.length}>{r.artifact || '—'}</td>}
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </>
      )}
    </>
  )
}
