/* 运行档案（契约 §2.2 #18）——一次运行的完整回放：
   状态怎么走的、每一步用了多久、审计怎么判的、日志包里都有什么。
   只读页，不在顶栏；从生成台「这一期的工具」进来。
   数据全部来自 GET /api/periods/{p}/archive（后端已把服务器绝对路径剥掉）。 */

import { useEffect, useState } from 'react'
import { getArchive, humanSize, type ArchiveData } from './api'
import { Icon } from './icons'
import { WaterfallRows } from './Waterfall'

/** 后端任务状态 → 馆员看得懂的话（src/agent/states.py 的十态） */
const STATUS_CN: Record<string, string> = {
  pending: '排队中', running: '运行中', retrying: '正在重试', stalled: '看起来卡住了',
  waiting_approval: '等待签单', completed: '已完成', warned: '完成（有告警）',
  escalated: '需要人接手', failed: '失败', cancelled: '已取消',
}
const AUDIT_LABEL: Record<string, string> = { pass: '通过', review: '待确认', fail: '不通过' }
const AUDIT_CLS: Record<string, string> = { pass: 'signed', review: 'stale', fail: '' }

function str(v: unknown): string {
  return v == null || v === '' ? '—' : String(v)
}

export function Archive({ period, approvalStatus }: { period: string | null; approvalStatus: string }) {
  const [d, setD] = useState<ArchiveData | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setD(null); setNote(null)
    getArchive(period)
      .then((a) => { if (alive) setD(a) })
      .catch((e) => {
        const h = e as { status?: number; body?: { hint?: string; error?: string } }
        if (!alive) return
        setNote(h.status === 403 ? '运行档案要管理员权限（用馆员账号登录后再来）。'
          : h.status === 404 ? (h.body?.hint ?? '这一期还没有运行档案（可能尚未出稿）。')
            : (h.body?.error ?? '读运行档案失败。'))
      })
    return () => { alive = false }
  }, [period])

  const job = d?.job ?? {}
  const env = (d?.env ?? {}) as Record<string, unknown>
  const deps = (env.deps ?? {}) as Record<string, string>
  const stats = (d?.stats ?? {}) as Record<string, unknown>

  return (
    <>
      <p className="hint" style={{ marginTop: 2 }}>
        <a href={`/app/?period=${period ? encodeURIComponent(period) : ''}`}>← 回生成台</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>

      {note && <div className="pending-box">{note}</div>}
      {!d && !note && <div className="pending-box">正在读这次运行的档案……</div>}

      {d && (
        <>
          {/* ===== 页头 ===== */}
          <section className="card" style={{ padding: '22px 24px' }}>
            <h1 style={{ fontSize: 24 }}>运行档案 · {d.period}</h1>
            <p className="fc-lead">
              这次运行的完整回放：状态怎么走的、每一步用了多久、审计怎么判的、日志包里都有什么。只读页——不改任何东西。
            </p>
            <dl className="ar-kv" style={{ marginTop: 12 }}>
              {d.job_id && <div><dt>任务号</dt><dd className="mono">{d.job_id}</dd></div>}
              {!!job.input && <div><dt>台账输入</dt><dd className="mono">{str(job.input)}</dd></div>}
              {!!job.actor && <div><dt>发起人</dt><dd>{str(job.actor)}</dd></div>}
            </dl>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 14 }}>
              {!!job.status && (
                <span className={`pill ${job.status === 'completed' ? 'signed' : job.status === 'warned' ? 'stale' : 'unsigned'}`}>
                  {STATUS_CN[String(job.status)] ?? String(job.status)}
                </span>
              )}
              {d.audit.exists && (
                <span className={`pill ${AUDIT_CLS[d.audit.verdict] ?? 'unsigned'}`}>
                  审计：{d.audit.verdict_label || AUDIT_LABEL[d.audit.verdict] || d.audit.verdict}
                </span>
              )}
              {!!d.logpack_url && (
                <a className="btn primary" href={d.logpack_url} style={{ marginLeft: 'auto' }}>
                  <Icon name="doc" size={19} />下载日志包（{d.logpack.n_files} 个文件 · {humanSize(d.logpack.bytes)}）
                </a>
              )}
            </div>
          </section>

          {/* ===== 01 状态机回放 ===== */}
          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="fc-no">01</span>状态机回放
              <span className="hint">{d.replay.n} 次迁移</span>
            </h2>
            {d.replay.chain.length ? (
              <div className="tablewrap" style={{ marginTop: 10 }}>
                <table className="ar-tbl">
                  <thead><tr><th style={{ width: '26%' }}>时刻</th><th style={{ width: '40%' }}>迁移</th><th>触发</th></tr></thead>
                  <tbody>
                    {d.replay.chain.map((r, i) => (
                      <tr key={i}>
                        <td className="mono">{r.ts || '—'}</td>
                        <td>
                          <span className="pill unsigned">{STATUS_CN[r.from] ?? r.from}</span>
                          <span className="muted" style={{ margin: '0 6px' }}>→</span>
                          <span className="pill signed">{STATUS_CN[r.to] ?? r.to}</span>
                          {r.synthetic && <span className="pill stale" style={{ marginLeft: 6 }}>合成</span>}
                        </td>
                        <td>{r.trigger || '—'}{r.attempt && r.attempt > 1 ? ` · 第 ${r.attempt} 次尝试` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="hint" style={{ marginTop: 8 }}>无状态迁移记录。</p>
            )}
            {d.replay.synthetic && (
              <p className="hint" style={{ marginTop: 10 }}>
                ⚠ {d.replay.note}——合成链只含确定发生过的迁移，不臆造自愈/升级环节。
              </p>
            )}
          </section>

          {/* ===== 02 任务瀑布 ===== */}
          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="fc-no">02</span>任务瀑布（各步耗时）
            </h2>
            {d.waterfall.length ? (
              <WaterfallRows rows={d.waterfall} totalSec={d.waterfall_total} summary={d.waterfall_summary} />
            ) : (
              <p className="pending-box" style={{ marginTop: 8 }}>
                {d.progress_missing
                  ? '进度记录读不到——文件可能随工作区迁移而改了位置，不是「这次运行没有记录」。'
                  : '这次运行没有留下每步记录（多半不是由演示站发起的）。'}
              </p>
            )}
          </section>

          {/* ===== 03 审计结论 ===== */}
          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="fc-no">03</span>审计结论
              <span className="hint">
                {d.audit.exists ? `${d.audit.generated_at} · 耗时 ${d.audit.elapsed_s} 秒` : '未执行'}
              </span>
            </h2>
            {d.audit.exists ? (
              <>
                <div className="tablewrap" style={{ marginTop: 10 }}>
                  <table className="ar-tbl">
                    <thead>
                      <tr><th style={{ width: '22%' }}>审计项</th><th style={{ width: '12%' }}>判定</th>
                        <th style={{ width: '26%' }}>实测</th><th>说明</th></tr>
                    </thead>
                    <tbody>
                      {d.audit.rows.map((it) => (
                        <tr key={it.id}>
                          <td><b>{it.title || it.id}</b></td>
                          <td>
                            <span className={`pill ${AUDIT_CLS[it.status] ?? 'unsigned'}`}>
                              {AUDIT_LABEL[it.status] ?? it.status}
                            </span>
                          </td>
                          <td className="mono">{it.metric || '—'}</td>
                          <td className="hint">{it.reason || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!!d.audit.truth_chain && (
                  <p className="hint" style={{ marginTop: 10 }}>
                    真值链：{typeof d.audit.truth_chain === 'string' ? d.audit.truth_chain : '—'}
                  </p>
                )}
              </>
            ) : (
              <p className="hint" style={{ marginTop: 8 }}>该期次没有审计记录——跑完流水线后由审计步骤生成。</p>
            )}
          </section>

          {/* ===== 04 / 05 ===== */}
          <div className="grid2" style={{ marginTop: 18 }}>
            <section className="card" style={{ padding: '20px 22px' }}>
              <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span className="fc-no">04</span>运行环境快照
              </h2>
              <dl className="ar-kv">
                <div><dt>Python</dt><dd className="mono">{str(env.python ?? deps.python)}</dd></div>
                <div><dt>平台</dt><dd className="mono">{str(env.platform)}</dd></div>
                {Object.entries(deps).filter(([k]) => k !== 'python').map(([k, v]) => (
                  <div key={k}><dt>{k}</dt><dd className="mono">{str(v)}</dd></div>
                ))}
                <div><dt>代码版本</dt><dd className="mono">{str(env.git_commit).slice(0, 12)}</dd></div>
                <div><dt>快照时间</dt><dd>{str(env.generated_at)}</dd></div>
              </dl>
              <p className="hint" style={{ marginTop: 8 }}>直跑路径不刷新快照——复现时以这份为准。</p>
            </section>

            <section className="card" style={{ padding: '20px 22px' }}>
              <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span className="fc-no">05</span>运行指标
              </h2>
              <dl className="ar-kv">
                <div><dt>当期 / 上期</dt><dd>{str(stats.period ?? d.period)} / {str(stats.prev)}</dd></div>
                <div><dt>数据校验</dt><dd>{stats.assertions_ok ? '全部通过' : `${str(stats.assertions_fail)} 处对不上`}</dd></div>
                <div><dt>预测 MAPE</dt><dd className="mono">{stats.predict_mape_overall == null ? '—' : `${stats.predict_mape_overall}%`}</dd></div>
                <div><dt>生成图表</dt><dd className="mono">{stats.charts == null ? '—' : `${stats.charts} 张`}</dd></div>
                <div><dt>全链路耗时</dt><dd className="mono">{stats.elapsed_sec == null ? '—' : `${stats.elapsed_sec} 秒`}</dd></div>
              </dl>
              <p className="hint" style={{ marginTop: 8 }}>数字全部来自台账单元格；运行期大模型不进入数据路径。</p>
            </section>
          </div>

          {/* ===== 06 产物与日志包 ===== */}
          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="fc-no">06</span>产物与日志包
              <span className="hint">日志包 {d.logpack.n_files} 个文件 · {humanSize(d.logpack.bytes)}</span>
            </h2>
            <div className="ar-arts">
              {!!d.logpack_url && (
                <a className="ar-art primary" href={d.logpack_url}>
                  <b>运行日志包（ZIP）</b>
                  <span className="m">回放最小集 · {d.logpack.n_files} 个文件 · {humanSize(d.logpack.bytes)}</span>
                </a>
              )}
              {d.artifacts.map((a) => (
                a.key === 'report' && approvalStatus !== 'signed'
                  ? <div className={`ar-art${a.primary ? ' primary' : ''}`} key={a.key} aria-disabled="true">
                      <b>{a.label}</b>
                      <span className="m">{a.name}{a.size ? ` · ${humanSize(a.size)}` : ''} · 未签发，管理员暂不能下载</span>
                    </div>
                  : <a className={`ar-art${a.primary ? ' primary' : ''}`} key={a.key} href={a.url}>
                      <b>{a.label}</b>
                      <span className="m">{a.name}{a.size ? ` · ${humanSize(a.size)}` : ''}</span>
                    </a>
              ))}
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              日志包只含回放所需文本件；完整产物快照（报告 docx、parquet、图表 PNG）在归档目录里。
            </p>
          </section>

          {/* ===== 07 轨迹文件 ===== */}
          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="fc-no">07</span>智能体轨迹文件
              <span className="hint">{d.trace_files.length} / 3</span>
            </h2>
            {d.trace_files.length ? (
              <div className="tablewrap" style={{ marginTop: 10 }}>
                <table className="ar-tbl">
                  <tbody>
                    {d.trace_files.map((n) => (
                      <tr key={n}><td className="mono">{n}</td><td className="hint">已随日志包归档</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="hint" style={{ marginTop: 8 }}>
                本次运行没有留下智能体轨迹文件——演示站主入口走流水线直跑，
                轨迹要由智能体编排器才写。档案页因此退化为「进度事件 + 任务状态」，这是<b>真实的记录缺口</b>，
                不是页面没渲染出来。
              </p>
            )}
          </section>
        </>
      )}
    </>
  )
}
