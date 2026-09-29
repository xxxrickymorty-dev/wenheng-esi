/* 分析台（工作区 4）——问文衡（qa 能力；契约 §2.2 #9）。字段面＝接口的 Answer：
   mode / backend / text / rule_text / notice / sources / shield（见 SPEC §1）。

   过渡版式说明（2026-09-29 · D2 接线）：此面板原先展示「按节解读」（旧 analyze 字段面），
   接口切到 qa 后先做**保活适配**；正式版式按 RICK 审过的
   `web/mockups/分析台-问答入口.html`（票 01）在 D5 落位（数字角标、工具回执、开关等）。

   🔴 硬边界（写进界面，不让馆员误以为数字是模型算的）：
     数字只来自台账；模型只组织语言、看不到任何数字（占位符 + 防护盾）；
     模型不可用自动回落规则版并在回答上如实标注；每个数字都能对回依据。 */

import { useState } from 'react'
import { req } from './api'
import { Icon } from './icons'
import { BigTable } from './BigTable'
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
  shield: { checked: number; passed: number }
  record_id: string | null
}

export function Analysis({ period }: { period: string | null }) {
  const [question, setQuestion] = useState('')
  const [data, setData] = useState<AnalyzeResp | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function run() {
    if (!period) return
    setBusy(true); setErr(null); setData(null)
    try {
      const r = await req<AnalyzeResp>('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ period, question }),
      })
      setData(r)
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setErr(h.body?.error ?? (h.status === 403 ? '问答需要管理员权限。'
        : h.status === 404 ? '这一期还没有可用产物（可能尚未出稿）。'
          : h.message ?? '作答失败'))
    } finally { setBusy(false) }
  }

  const modeText = !data ? '' :
    data.mode === 'model' ? `本次由模型组织语言（AI 生成 · ${data.backend}）` :
      data.mode === 'rule' ? '本次由规则版作答（数字与依据不受影响）' : data.mode

  return (
    <>
      {/* 先看数、再问：学科数据总览（读数版） */}
      <BigTable period={period} />

      <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="chart" size={22} />问文衡
          <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
        </h2>

        <p className="hint" style={{ marginTop: 10 }}>
          问这一期数据的问题（留空＝概述本期要点）。数字只来自台账；
          模型只组织语言、看不到任何数字；模型不可用时自动回落规则版并在回答上标注。
        </p>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="问一句，如：本期顶尖论文情况？"
            style={{
              font: 'inherit', padding: '9px 12px', color: 'inherit',
              border: '1px solid var(--line)', borderRadius: 9, background: 'var(--card)',
              width: 320,
            }}
          />
          <button className="btn primary" onClick={run} disabled={!period || busy}>
            <Icon name="play" size={20} />{busy ? '正在作答……' : '问一问'}
          </button>
          {data && (
            <span className="hint">
              {modeText} · 盾 {data.shield.passed} 个数字已登记
            </span>
          )}
        </div>

        {err && <div className="pending-box" style={{ marginTop: 14 }}>{err}</div>}
      </section>

      {data && (
        <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
          {data.notice && (
            <div className="pending-box" style={{ marginBottom: 12 }}>
              {data.notice}
              {data.record_id && <span className="hint"> · 留痕 {data.record_id}</span>}
            </div>
          )}
          {data.text.split(/\n{2,}/).map((p, i) => (
            <p key={i} style={{ margin: i ? '12px 0 0' : 0, fontFamily: 'var(--serif)', fontSize: 17.5, lineHeight: 1.85 }}>
              {p}
            </p>
          ))}

          {data.rule_text && data.rule_text !== data.text && (
            <details style={{ marginTop: 14 }}>
              <summary className="hint" style={{ cursor: 'pointer' }}>看规则版（同一条问题由规则库拼句）</summary>
              <p className="hint" style={{ whiteSpace: 'pre-wrap', marginTop: 8, lineHeight: 1.8 }}>
                {data.rule_text}
              </p>
            </details>
          )}

          {data.sources.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary className="hint" style={{ cursor: 'pointer' }}>
                回答依据（{data.sources.length} 处；第 k 个数字对应第 k 条）
              </summary>
              <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
                {data.sources.map((s) => (
                  <li key={s.index} className="hint" style={{ lineHeight: 1.8 }}
                      title={`${s.detail}（${s.pointer}）`}>
                    {s.index}. {s.label}：{s.value}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      {/* 两块解读挨着：先「问文衡」，再「灵活报告」（灵活） */}
      <Flexible period={period} />
    </>
  )
}
