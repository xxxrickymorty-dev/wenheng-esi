/* 分析台（工作区 4）——问文衡（qa 能力；契约 §2.2 #9）。
   版式按 rick 过审的减负稿 `web/mockups/分析台-问答入口.html`（2026-09-29，首屏 166 字）。

   字段面＝接口的 Answer：mode / backend / text / rule_text / notice / sources / shield。
   🔴 硬边界（界面上说清）：
     数字只来自台账；大模型只组织语言、看不见任何数字（占位符 + 防护盾）；
     模型不可用自动回落规则版并如实标注；每个数字点开可看来源；开关关掉只剩一行说明。 */

import { useEffect, useMemo, useState } from 'react'
import { getAiCapabilities, postAiSwitch, req, type AiCapability } from './api'
import { Icon } from './icons'
import { errorNote } from './lib/status'
import { Flexible } from './Flexible'

type Source = {
  index: number
  kind: string
  pointer: string
  label: string
  detail: string
  value: string
}
type AnalyzeResp = {
  mode: string
  backend: string
  text: string
  rule_text: string
  notice: string
  sources: Source[]
  receipts: { label: string; summary: string; elapsed_ms: number }[]
  shield: { checked: number; passed: number }
  record_id: string | null
}

/** 数字角标：第 k 个数字 ↔ sources[k-1]（后端已按出现次序对齐），点开看来源。 */
function NumberedText({ text, sources }: { text: string; sources: Source[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const parts = useMemo(() => {
    const nodes: React.ReactNode[] = []
    const re = /\d+(?:\.\d+)?/g
    let last = 0
    let k = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) {
      k += 1
      const idx = k
      if (m.index > last) nodes.push(text.slice(last, m.index))
      const src = sources[idx - 1]
      nodes.push(
        <span key={`n${k}`} className="rel-ib">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setOpen(open === idx ? null : idx) }}
            title={src ? `${src.label}：${src.value}` : undefined}
            style={{
              border: 0, borderBottom: '1px dotted var(--zhu)', padding: '1px 7px',
              margin: '0 1px', borderRadius: 7, background: 'var(--zhu-soft)',
              color: 'var(--zhu)', font: 'inherit', fontWeight: 650, cursor: 'pointer',
            }}
          >
            {m[0]}
          </button>
          {open === idx && src && (
            <span
              className="card an-pop"
              
            >
              <b className="ink">{src.label}</b>
              <br />
              {src.detail}
              <span className="hint"> · 台账数字</span>
            </span>
          )}
        </span>,
      )
      last = m.index + m[0].length
    }
    if (last < text.length) nodes.push(text.slice(last))
    return nodes
  }, [text, sources, open])

  return (
    <p className="serif-prose" 
       onClick={() => setOpen(null)}>
      {parts}
    </p>
  )
}

export function Analysis({ period }: { period: string | null }) {
  const [question, setQuestion] = useState('')
  const [data, setData] = useState<AnalyzeResp | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [showRule, setShowRule] = useState(false)
  const [qa, setQa] = useState<AiCapability | null>(null)
  const [qaBusy, setQaBusy] = useState(false)

  useEffect(() => {
    let live = true
    getAiCapabilities()
      .then((cs) => { if (live) setQa(cs.find((c) => c.id === 'qa') ?? null) })
      .catch(() => { /* 拿不到开关表就按「未关闭」显示——真门在后端 */ })
    return () => { live = false }
  }, [])

  const closed = !!qa && qa.stage === 'ready' && !qa.enabled

  async function run(q?: string) {
    const text = (q ?? question).trim()
    if (!period || busy) return
    if (q !== undefined) setQuestion(text)
    setBusy(true); setErr(null); setShowRule(false)
    try {
      const r = await req<AnalyzeResp>('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ period, question: text }),
      })
      setData(r)
    } catch (e) {
      const h = e as { body?: { error?: string } }
      setErr(h.body?.error ?? errorNote(e, '问答', {
        n404: '这一期还没有可用产物（可能尚未出稿）。',
        n409: '问答已被管理员关闭。',
      }))
    } finally { setBusy(false) }
  }

  async function toggleQa(next: boolean) {
    setQaBusy(true)
    try {
      await postAiSwitch('qa', next)
      setQa((c) => (c ? { ...c, enabled: next, notice: next ? '' : '此功能已由管理员关闭；数据与报告不受影响。' } : c))
    } finally { setQaBusy(false) }
  }

  return (
    <>
      <section className="card mt-18 pad-card-lg">
        <h2 className="h-sec h-lg">
          <Icon name="chart" size={22} />问文衡
          <span className="tag ml-6">{period ?? '（选择期次）'}</span>
          {qa && (
            <button
              className="btn ml-auto btn-lite"
              
              disabled={qaBusy}
              title="管理员可关闭问答；关闭后只留一行说明，分析台其余不受影响"
              onClick={() => toggleQa(!qa.enabled)}
            >
              <Icon name={qa.enabled ? 'play' : 'chart'} size={15} />
              {qa.enabled ? '已开启' : '已关闭'}
            </button>
          )}
        </h2>

        {closed ? (
          <div className="pending-box mt-14">
            {qa?.notice || '此功能已由管理员关闭；数据与报告不受影响。'}
            <button className="btn ml-12" disabled={qaBusy}
                    onClick={() => toggleQa(true)}>开启问文衡</button>
          </div>
        ) : (
          <>

            <div className="flex-g10 mt-14">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') run() }}
                placeholder="问一句，如：这期哪些学科离前 1% 最近？"
                aria-label="输入问题"
                style={{
                  flex: 1, minWidth: 0, font: 'inherit', padding: '11px 14px',
                  border: '1px solid var(--line)', borderRadius: 10,
                  background: 'var(--card)', color: 'inherit',
                }}
              />
              <button className="btn primary" onClick={() => run()} disabled={!period || busy}>
                <Icon name="play" size={20} />{busy ? '正在作答……' : '问一问'}
              </button>
            </div>

            <div className="rowc8 mt-10">
              <span className="hint">试试：</span>
              {['哪些学科离前 1% 最近？', '前 1% 学科有几门？'].map((q) => (
                <button
                  key={q}
                  className="btn chip-round"
                  
                  disabled={!period || busy}
                  onClick={() => run(q)}
                >
                  {q}
                </button>
              ))}
            </div>

            {err && <div className="pending-box mt-14">{err}</div>}
          </>
        )}
      </section>

      {data && (
        <section className="card mt-16 pad-18-22">
          <div className="an-toolbar">
            <span className="pill signed">问</span>
            <b>{question || '（概述本期要点）'}</b>
            <span className="row-end">
              <span className={`pill ${data.mode === 'model' ? 'signed' : 'stale'}`}>
                {data.mode === 'model' ? '大模型作答' : '规则版作答'}
              </span>
              <span className="hint" title="工具读出台账数字 → 登记进防护盾 → 大模型只组织语言；任一环节不过，整段回退规则版。">?</span>
            </span>
          </div>

          {data.receipts.length > 0 && (
            <details className="an-snippet">
              <summary className="hint cursor-p">
                本次调度 {data.receipts.length} 个工具（只读）
              </summary>
              <ul className="hint an-list">
                {data.receipts.map((r, i) => (
                  <li key={i}>{r.label}：{r.summary}（{r.elapsed_ms} 毫秒）</li>
                ))}
              </ul>
            </details>
          )}

          {data.notice && (
            <div className="pending-box mt-10 pad-10-14">
              {data.notice}
              {data.mode === 'rule' && (
                <button className="btn ml-12" disabled={busy}
                        onClick={() => run()}>重试</button>
              )}
              {data.record_id && <span className="hint"> · 留痕 {data.record_id}</span>}
            </div>
          )}

          <div className="pad-12-0-2">
            {showRule
              ? <p className="serif-prose">{data.rule_text}</p>
              : <NumberedText text={data.text} sources={data.sources} />}
          </div>

          <div className="an-footer">
            <span className="pill ok">盾 · {data.shield.passed} 个数字已登记</span>
            <span className="hint">点数字看来源</span>
            <span className="flex-1" />
            {data.rule_text && data.rule_text !== data.text && (
              <button className="btn fs-13" onClick={() => setShowRule(!showRule)}>
                {showRule ? '看模型版' : '看规则版'}
              </button>
            )}
          </div>
        </section>
      )}

      <details className="card mt-16 pad-14-18">
        <summary className="hint cursor-p list-none">
          说明 · 口径与来源
        </summary>
        <ul className="hint an-list2">
          <li>数字只来自馆员维护的台账与派生产物；问答不改动任何数据。</li>
          <li>大模型只组织语言、不计算数字；数字由工具读取并逐一登记（防护盾），校验不过整段回退规则版。</li>
          <li>提问会带一小段数据摘要发送到云端大模型，仅用于生成回答；管理员可整体关闭；记录存运行档案，可回放。</li>
        </ul>
      </details>

      {/* 两块解读挨着：先「问文衡」，再「灵活报告」（灵活） */}
      <Flexible period={period} />
    </>
  )
}
