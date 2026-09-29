/* 分析台第二块 · 灵活报告（第二条产线）——契约 #21。
   与「按节解读」是一对：那份回答「这一期该报什么」，这份回答「某个问题怎么看」。
   正文是后端渲好的 body_html（后端自己的 mdview.render，图指向
   /p/<期次>/flexible/chart/<intent>/<name>）——前端只摆进去：不引 md 渲染器、不改一个字。
   ⚠ innerHTML 用在这里的前提：正文来自本仓产线产物、无任何用户输入（与老站同一渲染器）；
   将来若允许人工往里写正文，这里必须先过白名单清洗。 */

import { useEffect, useState } from 'react'
import { getFlexible, runFlexible, type FlexibleData } from './api5'
import { Icon } from './icons'

export function Flexible({ period }: { period: string | null }) {
  const [d, setD] = useState<FlexibleData | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [gen, setGen] = useState(false)
  const [intent, setIntent] = useState('')
  const [disc, setDisc] = useState('')

  useEffect(() => {
    if (!period) return
    let alive = true
    setD(null); setNote(null); setBusy(true); setIntent('')
    ;(async () => {
      try {
        const j = await getFlexible(period)
        if (!alive) return
        setD(j)
        if (j.intents.length) setIntent(j.intents[0].id)
      } catch (e) {
        const h = e as { status?: number; body?: { hint?: string; error?: string } }
        if (alive) {
          setNote(h.status === 403 ? '灵活报告要管理员权限（用馆员账号登录后再来）。'
            : (h.body?.error ?? '读灵活报告失败。'))
        }
      } finally {
        if (alive) setBusy(false)
      }
    })()
    return () => { alive = false }
  }, [period])

  async function pick(which: string) {
    if (!period || which === d?.cur) return
    setBusy(true); setNote(null)
    try {
      setD(await getFlexible(period, which))
    } catch {
      setNote('切换这份稿失败了。')
    } finally { setBusy(false) }
  }

  async function onGen() {
    if (!period || !intent) return
    setGen(true); setNote(null)
    try {
      const r = await runFlexible(period, { intent, disc: disc.trim() || undefined })
      const j = await getFlexible(period, intent)
      setD(j)
      setNote(`已生成${j.cur ? `「${j.reports.find((x) => x.intent === j.cur)?.title ?? j.cur}」` : ''}`
        + ` · ${r.elapsed} 秒${r.n_charts ? ` · ${r.n_charts} 张图` : ''}`
        + `（产出在 out/${period}/flexible/，与复刻报告产物互不重叠）`)
    } catch (e) {
      const h = e as { body?: { hint?: string; error?: string }; message?: string }
      setNote(h.body?.hint ?? h.body?.error ?? h.message ?? '生成失败。')
    } finally { setGen(false) }
  }

  const curTitle = d?.reports.find((x) => x.intent === d.cur)?.title ?? d?.cur ?? ''

  return (
    <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
      <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Icon name="doc" size={22} />灵活报告 · 第二条产线
        <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
        <span className="pill stale">内部参考件</span>
      </h2>

      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        与上面那份是一对：上面回答<b>这一期该报什么</b>；这里回答<b>某个问题怎么看</b>——
        规划器自主挑学科、定章节、配图，产出<b>内部参考件</b>：不套母版、不带盖章位、不作为对外报送材料
        （对外件走复刻报告那条线）。
      </p>

      <div className="fx-form">
        <label>分析意图
          <select value={intent} onChange={(e) => setIntent(e.target.value)}>
            {(d?.intents ?? []).map((i) => <option key={i.id} value={i.id}>{i.cn}</option>)}
          </select>
        </label>
        <label>指定学科（可空 = 由规划器挑）
          <input value={disc} onChange={(e) => setDisc(e.target.value)} placeholder="如 Engineering" />
        </label>
        <button className="btn primary" onClick={onGen} disabled={!period || !intent || gen}>
          <Icon name="play" size={19} />{gen ? '正在出稿……' : '生成分析稿'}
        </button>
      </div>
      <p className="fx-note">
        产出落在 <b className="mono">out/{period ?? '—'}/flexible/</b>，与复刻报告产物互不重叠；
        按下后页面没动静是正常的（约几秒），别连点。
      </p>

      {!!d?.reports.length && (
        <div className="fx-chips">
          <span>已出稿：</span>
          {d.reports.map((r) => (
            <button key={r.intent} className={r.intent === d.cur ? 'on' : ''}
                    onClick={() => pick(r.intent)}>
              {r.title || r.intent}
              {typeof r.meta?.n_charts === 'number' ? ` · ${r.meta.n_charts} 图` : ''}
              {typeof r.meta?.generated_at === 'string' && r.meta.generated_at
                ? ` · ${String(r.meta.generated_at).slice(5, 16)}` : ''}
            </button>
          ))}
        </div>
      )}

      {note && <div className="pending-box" style={{ marginTop: 12 }}>{note}</div>}
      {busy && !d && <div className="pending-box" style={{ marginTop: 12 }}>正在读已出稿……</div>}

      {d && !busy && !d.body_html && (
        <p className="hint" style={{ marginTop: 12 }}>
          这一期还没有灵活报告——选好意图点「生成分析稿」；生成后这里会显示正文（正文由后端渲染，图是产物里的真图）。
        </p>
      )}

      {d?.body_html && (
        <>
          {curTitle && <p className="hint" style={{ marginTop: 12 }}>正在看：<b>{curTitle}</b></p>}
          <article className="fx-md" dangerouslySetInnerHTML={{ __html: d.body_html }} />
        </>
      )}
    </section>
  )
}
