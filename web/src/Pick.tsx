/* 出报告 · ②选材（票 07 · 最省版）——报告大纲（只读）+ 「本轮办哪些节」。
   数据只来自 GET /api/periods/{period}/outline（服务端只读，由产物推导，不写任何文件）。
   **最省版**：这一屏只记范围——出稿一律全出、母版一个字不动；不落库，每次进屏重选。
   不删节、不清槽、不跨期搬内容。
   静态稿：web/mockups/②选材（静态稿）.html；契约：§2.2 outline。 */

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { getOutline, type Outline, type OutlineSection } from './api'
import { Icon } from './icons'
import { errorNote } from './lib/status'

export function Pick({ period }: { period: string | null }) {
  const [d, setD] = useState<Outline | null>(null)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)
  /* 勾选：默认全选（章 + 节）。不落库，重进屏即重置。 */
  const [off, setOff] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    if (!period) return
    setErr('')
    try {
      const o = await getOutline(period)
      setD(o)
      setOff(new Set())
      setSaved(false)
    } catch (e) {
      setErr(errorNote(e, '报告大纲'))
    }
  }, [period])

  useEffect(() => { void load() }, [load])

  const allIds = useMemo(
    () => (d ? d.sections.flatMap((s) => [s.id, ...(s.subs ?? []).map((x) => x.id)]) : []),
    [d])
  const toggle = (id: string) => setOff((cur) => {
    const n = new Set(cur)
    if (n.has(id)) n.delete(id); else n.add(id)
    return n
  })

  if (!period) return <p className="pending-box mt-0">先在上方选一个期次。</p>
  if (err) return <p className="pending-box mt-0">{err}　<a href="#main" onClick={(e) => { e.preventDefault(); void load() }}>重试</a></p>
  if (!d) return <p className="hint mt-12">正在读报告大纲……</p>

  const selected = allIds.filter((id) => !off.has(id))
  const skipped = d.sections.filter((s) => off.has(s.id)).map((s) => s.label)
  const toggleTop = (s: OutlineSection, on: boolean) => setOff((cur) => {
    const n = new Set(cur)
    for (const id of [s.id, ...(s.subs ?? []).map((x) => x.id)]) { if (on) n.delete(id); else n.add(id) }
    return n
  })
  const copySkip = async () => {
    const text = skipped.length
      ? `本轮不办（${d.period}）：${skipped.join('；')}`
      : `本轮不办（${d.period}）：无，全部办理。`
    try { await navigator.clipboard.writeText(text) } catch { /* 剪贴板不可用就算了 */ }
    setSaved(true)
  }

  return (
    <>
      <div className="h-sec pick-title">
        <b>出报告 · ② 选材</b>
        <span className="hint">这一期要办哪些节，你在这里勾。<b>只记范围</b>——出稿仍全出、母版一个字不动；没勾的标「本轮不办」。</span>
      </div>

      <section className="card mt-16 pad-card">
        <div className="fold-lead hint">
          <b>报告大纲 · {d.period}</b>
          <span className="ml-auto">依据：<span className="pick-mono">{d.slotsTotal} 个槽位</span>（版式类 {d.slotsUnassigned} 不归章）</span>
        </div>
        <table className="pick-tbl">
          <tbody>
            {d.sections.map((s) => {
              const on = !off.has(s.id)
              return (
                <Fragment key={s.id}>
                  <tr className={on ? '' : 'skipped'}>
                    <td className="pick-nm">
                      <label className="pick-box-wrap">
                        <input type="checkbox" checked={on} onChange={(e) => toggleTop(s, e.target.checked)} />
                        <span className="pick-box" aria-hidden="true">{on ? '✓' : ''}</span>
                        <b>{s.label}</b>
                      </label>
                      {!on && <span className="pill unsigned ml-8">本轮不办</span>}
                    </td>
                    <td className="pick-src">{s.source}</td>
                    <td className="pick-slots">
                      {s.slots ? `${s.slots} 槽位` : '—'}
                      {!s.ready && <span className="pill stale ml-8">未就绪</span>}
                    </td>
                  </tr>
                  {(s.subs ?? []).map((x) => {
                    const subOn = !off.has(x.id)
                    return (
                      <tr key={x.id} className={`sub${subOn ? '' : ' skipped'}`}>
                        <td className="pick-nm">
                          <label className="pick-box-wrap">
                            <input type="checkbox" checked={subOn} onChange={() => toggle(x.id)} />
                            <span className="pick-box" aria-hidden="true">{subOn ? '✓' : ''}</span>
                            · {x.label}
                          </label>
                        </td>
                        <td className="pick-src" />
                        <td className="pick-slots">{x.slots ? `${x.slots}` : '—'}</td>
                      </tr>
                    )
                  })}
                </Fragment>
              )
            })}
          </tbody>
        </table>

        <div className="pick-foot">
          <span className="hint">
            已选 <b>{selected.length}</b> / {allIds.length} 节
            {skipped.length ? <>　·　本轮不办：<b>{skipped.join('；')}</b></> : null}
          </span>
          <span className="ml-auto roww">
            <button className="btn small" onClick={() => setOff(new Set())}>全选</button>
            <button className="btn small" onClick={() => setOff(new Set(allIds))}>全不选</button>
            <button className="btn small" disabled={saved} onClick={() => void copySkip()}>
              {saved ? '已复制' : '复制「本轮不办清单」'}
            </button>
            <button className="btn small" disabled={saved} onClick={() => setSaved(true)}>
              <Icon name="check" size={18} />记住本轮范围
            </button>
          </span>
        </div>
        {saved && (
          <p className="hint mt-10">
            已记下（<b>本屏内，不落库</b>）——离开这一屏即重置。要留底，用上面的「复制」抄进审核台批注。
          </p>
        )}
      </section>

      <div className="pick-note mt-16">
        <b>最省版</b>：这一屏<b>只记范围</b>——出稿一律全出、母版一个字不动（不删节、不清槽、不搬别期内容）。
        <ul>
          <li>数据只读：章节与槽位由后端从产物推导，<b>不写任何文件</b>。</li>
          <li>「本轮不办」只在本屏表达，供你抄进批注；<b>不影响出稿</b>。</li>
        </ul>
      </div>
    </>
  )
}
