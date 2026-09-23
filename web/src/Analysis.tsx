/* 分析台（工作区 4）——按节的解读 + 数字防护盾。
   契约 §2.2 #9；后端已交付 POST /api/analyze。
   🔴 这条线的硬边界（写进界面，不让馆员误以为是大模型在写）：
     数字只来自台账；正文由**确定性句骨架**出（`backend: "sentences"`）；
     运行期 LLM 不进数据路径。每一段都过「数字防护盾」，界面把盾的结果显示出来。 */

import { useState } from 'react'
import { req } from './api'
import { Icon } from './icons'

type Shield = { key: string; n_numbers: number; protected_len: number }
type AnalyzeResp = {
  period: string
  prev?: string
  text: Record<string, string>
  shields: Shield[]
  n_sections: number
  backend: string
}

export function Analysis({ period }: { period: string | null }) {
  const [scope, setScope] = useState('')
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
        body: JSON.stringify({ period, scope }),
      })
      setData(r)
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setErr(h.body?.error ?? (h.status === 403 ? '分析需要管理员权限。'
        : h.status === 404 ? '这一期还没有 overview_facts.json（可能尚未出稿）。'
          : h.message ?? '分析失败'))
    } finally { setBusy(false) }
  }

  const shieldOf = (k: string) => data?.shields.find((s) => s.key === k)

  return (
    <>
      <section className="card" style={{ padding: '22px 24px' }}>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="chart" size={22} />分析 · 按节解读
          <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
        </h2>

        <div className="pending-box" style={{ marginTop: 14 }}>
          <b>这条线的边界（先说清楚）</b>
          <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
            <li>数字只来自台账；正文由<b>确定性句骨架</b>拼出，<b>运行期大模型不进数据路径</b>。</li>
            <li>每一段都过「数字防护盾」：段里的每个数字都被登记（下表右侧的盾就是登记结果）。</li>
            <li>所以这里输出的是"可核的解读"，不是聊天。要问问题请走分析台之外的问答入口（暂未接）。</li>
          </ul>
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 16, flexWrap: 'wrap' }}>
          <label>
            只看某一节（可空）
            <input
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              placeholder="如 概述 / 趋势 / bigtable"
              style={{
                marginLeft: 10, font: 'inherit', padding: '9px 12px', color: 'inherit',
                border: '1px solid var(--line)', borderRadius: 9, background: 'var(--card)', width: 220,
              }}
            />
          </label>
          <button className="btn primary" onClick={run} disabled={!period || busy}>
            <Icon name="play" size={20} />{busy ? '正在生成……' : '生成解读'}
          </button>
          {data && (
            <span className="hint">
              共 {data.n_sections} 节 · 后端 {data.backend === 'sentences' ? '句骨架（未启用模型润色）' : data.backend}
              {data.prev ? ` · 对照期 ${data.prev}` : ''}
            </span>
          )}
        </div>

        {err && <div className="pending-box" style={{ marginTop: 14 }}>{err}</div>}
      </section>

      {data && (
        <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
          {Object.entries(data.text).map(([key, text]) => {
            const sh = shieldOf(key)
            return (
              <article key={key} style={{ paddingBottom: 16, marginBottom: 16, borderBottom: '1px solid var(--line-2)' }}>
                <h3 style={{ fontSize: 16, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span className="mono" style={{ color: 'var(--ink-3)', fontSize: 13.5 }}>{key}</span>
                  {sh && (
                    <span className="pill signed" title="这一段里的数字全部登记在防护盾里">
                      盾 · {sh.n_numbers} 个数字已登记
                    </span>
                  )}
                </h3>
                <p style={{ margin: '8px 0 0', fontFamily: 'var(--serif)', fontSize: 17.5, lineHeight: 1.85 }}>
                  {text}
                </p>
              </article>
            )
          })}
        </section>
      )}
    </>
  )
}
