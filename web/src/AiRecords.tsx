/* 运行档案 04 · 问文衡——问答与模型调用（票 06 块；契约 §2.2 #30）。
   版式按 rick 过审的 `web/mockups/运行档案-问答与模型调用.html`（2026-09-29）。

   每条记录展开就是一条链：问 →（工具）→ 模型 → 校验。
   记录只读、是摘要（问题/模式/后端/回落原因/盾计数/耗时），不含回答正文与提示词；
   主体流水线始终零模型——模型只出现在问答与决策环。 */

import { useEffect, useState } from 'react'
import { getAiCalls, type AiCall, type AiCalls } from './api'

const CAP_CN: Record<string, string> = {
  qa: '问文衡', review: '复核参谋', diagnose: '诊断参谋', brief: '期次导读',
  polish: '解读润色',
}

/** 回落原因码 → 馆员看得懂的话（不出现内部词） */
const FALLBACK_CN: Record<string, string> = {
  'brain_error:timeout': '模型超时未返回',
  'brain_error:unreachable': '模型连不上',
  'brain_error:rate_limit': '模型限额已满',
  'brain_error:egress_budget': '本次内容超出外发上限',
  'brain_error:bad_response': '模型返回不符合格式',
  'empty_reply': '模型未返回正文',
  'off_topic': '作答未引用本期数据',
  'shield_reject': '未通过数字校验',
  'record_failed': '留痕写失败，改用规则版',
  'calls_unsupported': '请求了未开放的工具',
}

function fallbackText(code: string): string {
  if (FALLBACK_CN[code]) return FALLBACK_CN[code]
  return code.startsWith('brain_error:') ? '模型调用失败' : code
}

function hhmm(ts: string): string {
  const m = ts.match(/T(\d{2}:\d{2})/)
  return m ? m[1] : (ts || '—')
}

export function AiRecords({ period }: { period: string | null }) {
  const [d, setD] = useState<AiCalls | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [kind, setKind] = useState<'all' | 'model' | 'rule'>('all')
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    if (!period) { setD(null); return }
    let alive = true
    setD(null); setErr(null)
    getAiCalls(period)
      .then((a) => { if (alive) { setD(a); setOpen(a.calls[0]?.record_id ?? null) } })
      .catch((e) => {
        const h = e as { status?: number; body?: { hint?: string; error?: string } }
        if (!alive) return
        setErr(h.status === 404 ? '这一期还没有产物，暂时没有问答记录。'
          : h.body?.error ?? '读问答记录失败。')
      })
    return () => { alive = false }
  }, [period])

  const filtered = (d?.calls ?? []).filter((c) => kind === 'all' ? true
    : kind === 'model' ? c.mode === 'model' : (c.fallback !== null || c.mode === 'rule'))

  return (
    <>
      {/* ===== 问答记录（编号随档案页减负顺延：01 过程回放 → 02 问答记录 → 03 审计） ===== */}
      <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span className="fc-no">02</span>问文衡 · 问答记录
          <span className="hint">问 → 工具 → 模型 → 校验</span>
          <span className="hint" title="记录里有什么：问题、每次工具调用（读了什么、花了多久）、模型调用（用了哪个模型、成没成）、校验结果（盾）。不含回答正文与提示词。">?</span>
        </h2>

        {err && <p className="pending-box" style={{ marginTop: 10 }}>{err}</p>}
        {!d && !err && <p className="hint" style={{ marginTop: 10 }}>正在读问答记录……</p>}

        {d && (
          <>
            <p className="hint" style={{ marginTop: 10 }}>
              本期 {d.stats.n} 次 · 模型作答 {d.stats.model} · 回落 {d.stats.fallback}
              {' · '}平均 {d.stats.avg_sec} 秒{d.stats.last_ts ? ` · 最近一次 ${d.stats.last_ts.replace('T', ' ').slice(0, 16)}` : ''}
            </p>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              {([['all', '全部'], ['model', '模型作答'], ['rule', '规则回落']] as const).map(([k, label]) => (
                <button key={k} className="btn"
                        style={{
                          borderRadius: 999, padding: '5px 13px', fontSize: 13,
                          ...(kind === k ? { borderColor: 'var(--zhu)', background: 'var(--zhu-soft)', color: 'var(--zhu)', fontWeight: 650 } : {}),
                        }}
                        onClick={() => setKind(k)}>
                  {label}
                </button>
              ))}
            </div>

            {filtered.length === 0 ? (
              <p className="hint" style={{ marginTop: 12 }}>
                {d.stats.n === 0
                  ? '本期还没有问答与模型调用记录——从本条线启用起的调用才会记录，启用前的历史运行不猜、不补造。'
                  : '当前筛选下没有记录。'}
              </p>
            ) : (
              <div style={{ marginTop: 10 }}>
                {filtered.map((c) => <Row key={c.record_id} c={c}
                                          open={open === c.record_id}
                                          onToggle={() => setOpen(open === c.record_id ? null : c.record_id)} />)}
              </div>
            )}
          </>
        )}
      </section>

      {/* ===== 运行级 · 模型参与（附在问答记录后，不占编号） ===== */}
      <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          运行级 · 模型参与
          <span className="hint">主流水线零大模型</span>
        </h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
          <span className="pill unsigned">主体步骤 · 零模型</span>
          <span className="pill signed">问答 · {d?.stats.n ?? 0} 次
            {d && d.stats.n > 0 ? `（模型 ${d.stats.model} · 回落 ${d.stats.fallback}）` : ''}</span>
        </div>
      </section>
    </>
  )
}

function Row({ c, open, onToggle }: { c: AiCall; open: boolean; onToggle: () => void }) {
  const isModel = c.mode === 'model'
  const shortId = c.record_id ? `#${c.record_id.slice(-4)}` : '—'
  return (
    <div style={{
      borderTop: '1px solid var(--line-2)', padding: '9px 0', cursor: 'pointer',
    }} onClick={onToggle}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="mono hint">{hhmm(c.ts)}</span>
        <span style={{ fontWeight: 650 }}>{c.question || '（概述本期要点）'}</span>
        {c.capability && c.capability !== 'qa' && (
          <span className="pill unsigned">{CAP_CN[c.capability] ?? c.capability}</span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`pill ${isModel ? 'signed' : 'stale'}`}>{isModel ? '模型作答' : '规则回落'}</span>
          <span className="pill ok">校验 {c.shield.passed}/{c.shield.checked}</span>
          <span className="hint mono">{shortId} · {(c.elapsed_ms / 1000).toFixed(1)} 秒</span>
        </span>
      </div>

      {open && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="pill unsigned">问 · {CAP_CN[c.capability] ?? c.capability ?? '—'}</span>
          <span className="hint">→</span>
          {c.n_tools > 0 && (
            <>
              <span className="pill unsigned">工具调用 · {c.n_tools} 次</span>
              <span className="hint">→</span>
            </>
          )}
          {isModel ? (
            <span className="pill signed">云模型作答 · {c.backend.replace(/^openai:/, '')}</span>
          ) : (
            <>
              {c.fallback && <span className="pill stale">模型调用 · {fallbackText(c.fallback)}</span>}
              {c.fallback && <span className="hint">→</span>}
              <span className="pill unsigned">规则作答</span>
            </>
          )}
          <span className="hint">→</span>
          <span className="pill ok">校验 · 盾 {c.shield.passed}/{c.shield.checked} 个数字登记</span>
          {c.fallback && (
            <p className="hint" style={{ flexBasis: '100%', margin: '4px 0 0' }}>
              回落原因：{fallbackText(c.fallback)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
