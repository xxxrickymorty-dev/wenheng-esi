/* 运行档案（契约 §2.2 #18）——一次运行的完整回放：
   状态怎么走的、每一步用了多久、审计怎么判的、日志包里都有什么。
   只读页；从顶栏进来；「这一期的工具」折块也在本页（2026-10-24 迁入）。
   数据全部来自 GET /api/periods/{p}/archive（后端已把服务器绝对路径剥掉）。

   减负版（2026-09-29，diji 票 12 对照稿过审）：同源数据一份只画一遍——
   01 过程回放（链＋瀑布各一次，删旧「01 表」「02 瀑布」「03 调度」三块重复）·
   页头凭据折进「任务凭据」· 审计失败优先（通过项折起）· 编号 01→04 连续。
   极简稿（2026-10-24，rick 拍板）：删页首回链行、页题导语、审计末行时间戳、
   轨迹折块说明性小字；下载按钮只留「下载日志包」——只留数据、状态与错误。 */

import { useEffect, useState } from 'react'
import { getAcquisition, getArchive, humanSize, type AcquisitionState, type ArchiveData } from './api'
import { AiRecords } from './AiRecords'
import { Icon } from './icons'
import { buildArchiveStory } from './lib/archiveStory'
import { AUDIT_LABEL, acqGroupLabel, errorNote, taskLabel } from './lib/status'
import { WaterfallRows } from './Waterfall'

const AUDIT_CLS: Record<string, string> = { pass: 'signed', review: 'stale', fail: '' }

function str(v: unknown): string {
  return v == null || v === '' ? '—' : String(v)
}

export function Archive({ period, approvalStatus }: { period: string | null; approvalStatus: string }) {
  const [d, setD] = useState<ArchiveData | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [acq, setAcq] = useState<AcquisitionState | null>(null)

  useEffect(() => {
    if (!period) { setAcq(null); return }
    let alive = true
    getAcquisition(period)
      .then((a) => { if (alive) setAcq(a) })
      .catch(() => { if (alive) setAcq(null) })     // 没有下载数据记录就整块不显示（不占屏）
    return () => { alive = false }
  }, [period])

  useEffect(() => {
    if (!period) return
    let alive = true
    setD(null); setNote(null)
    getArchive(period)
      .then((a) => { if (alive) setD(a) })
      .catch((e) => {
        if (!alive) return
        setNote(errorNote(e, '运行档案'))
      })
    return () => { alive = false }
  }, [period])

  const job = d?.job ?? {}
  const env = (d?.env ?? {}) as Record<string, unknown>
  const deps = (env.deps ?? {}) as Record<string, string>
  const stats = (d?.stats ?? {}) as Record<string, unknown>

  const auditRows = d?.audit.exists ? d.audit.rows : []
  const auditBad = auditRows.filter((r) => r.status !== 'pass')
  const auditPass = auditRows.filter((r) => r.status === 'pass')
  const story = d ? buildArchiveStory(d, acq, approvalStatus) : []

  return (
    <>
      {note && <div className="pending-box">{note}</div>}
      {!d && !note && <div className="pending-box">正在读这次运行的档案……</div>}

      {d && (
        <>
          {/* ===== 页头 ===== */}
          <section className="card pad-card-lg">
            <h1 className="fs-24">运行档案 · {d.period}</h1>
            <div className="rowc mt-14">
              {!!job.status && (
                <span className={`pill ${job.status === 'completed' ? 'signed' : job.status === 'warned' ? 'stale' : 'unsigned'}`}>
                  {taskLabel(String(job.status))}
                </span>
              )}
              {d.audit.exists && (
                <span className={`pill ${AUDIT_CLS[d.audit.verdict] ?? 'unsigned'}`}>
                  审计：{d.audit.verdict_label || AUDIT_LABEL[d.audit.verdict] || d.audit.verdict}
                </span>
              )}
              {!!d.logpack_url && (
                <a className="btn primary ml-auto" href={d.logpack_url} >
                  <Icon name="doc" size={19} />下载日志包
                </a>
              )}
            </div>
          </section>

          {/* ===== 故事条（2026-10-20）：五步给评委看，日志表格留给技术复盘 ===== */}
          <section className="ar-story" aria-label="这一期怎么做出来的">
            {story.map((s) => (
              <div className={`ar-story-step ${s.state}`} key={s.key}>
                <span className="ar-story-k">{s.title}</span>
                <b>{s.value}</b>
                <small>{s.note}</small>
              </div>
            ))}
          </section>

          {/* ===== 任务凭据（页头 kv 折进来；减负：首屏不再铺三条凭据） ===== */}
          {(d.job_id || job.input || job.actor) && (
            <details className="fold">
              <summary>任务凭据<span className="sm">任务号 · 发起人 · 输入</span></summary>
              <div className="fold-inner">
                <p className="mono fs-13 m-0 lh-19">
                  {d.job_id && <>任务号 {d.job_id}<br /></>}
                  {!!job.input && <>台账输入 {str(job.input)}<br /></>}
                  {!!job.actor && <>发起人 {str(job.actor)}</>}
                </p>
              </div>
            </details>
          )}

          {/* ===== 00 下载数据记录（X3）：下载与并入的留痕；没有下载数据记录时整块不显示 ===== */}
          {acq?.started && (
            <details className="fold">
              <summary>
                下载数据记录 · 下载与并入
                <span className="sm">
                  核验 {acq.totals?.verified ?? 0} / {acq.totals?.expected ?? '—'}
                  {acq.copy?.state === 'merged' ? ' · 已并入台账' : acq.copy?.state === 'review' ? ' · 待核对' : ''}
                </span>
              </summary>
              <div className="fold-inner">
                <p className="hint mt-0">
                  数据期：ESI {acq.data_period?.esi || '—'} · InCites 截至 {acq.data_period?.incites || '—'}
                  {'；'}状态最后更新 {acq.updated_at || '—'}。
                </p>
                <ul className="rv-todo mt-6">
                  {(acq.groups ?? []).map((g, i) => (
                    <li key={g.id ?? i}>
                      <span className="rv-todo-t">{g.title}</span>
                      <span className="mono rv-todo-v">{g.verified ?? 0} / {g.files?.length ?? '—'}</span>
                      <span className="rv-todo-v">{acqGroupLabel(g.state)}</span>
                    </li>
                  ))}
                </ul>
                <p className="hint">
                  {acq.copy?.state === 'merged'
                    ? `已并入主台账${acq.copy.merged_at ? `：${acq.copy.merged_at}` : ''}`
                      + `${acq.copy.merged_by ? ` · 操作人：${acq.copy.merged_by}` : ''}`
                      + (acq.copy.merged_at ? '（写前有备份；写后逐格核对过）'
                        : '（本期并入早于下载数据留痕，未记时刻与操作人）')
                    : acq.copy?.state === 'review'
                      ? '已建好当期核对副本，还没并入主台账——核对通过后才落笔。'
                      : '还没下载数据，也没有并入记录。'}
                </p>
              </div>
            </details>
          )}

          {/* ===== 01 过程回放（链 + 瀑布，同一份数据只此一处；diji 票 12 合并 01/02/03） ===== */}
          <section className="card mt-18 pad-card">
            <h2 className="h-sec">
              过程回放
              <span className="hint">
                {d.replay.n} 次迁移 · {d.waterfall.length} 步
                {d.waterfall_total ? ` · 全程 ${d.waterfall_total} 秒` : ''}
              </span>
              <span className="hint"
                    title="状态与每一步的耗时都来自运行档案；直跑线不产生状态流水，迁移链由任务记录合成——只含确定发生过的迁移，不臆造自愈/升级环节。">?</span>
            </h2>
            {d.replay.chain.length ? (
              <div className="ar-chain mt-10">
                {d.replay.chain.map((r, i) => (
                  <span className="ar-chain-node" key={i}>
                    <span>{taskLabel(r.from)}<i> → </i>{taskLabel(r.to)}</span>
                    <small>{r.ts || '—'}{r.trigger ? ` · ${r.trigger}` : ''}{r.synthetic ? ' · 补记' : ''}</small>
                  </span>
                ))}
              </div>
            ) : (
              <p className="hint mt-6">无迁移记录。</p>
            )}
            <div className="mt-12">
              {d.waterfall.length ? (
                <WaterfallRows rows={d.waterfall} totalSec={d.waterfall_total} summary={d.waterfall_summary} />
              ) : (
                <p className="pending-box mt-8">
                  {d.progress_missing
                    ? '进度记录读不到——文件可能随工作区迁移而改了位置，不是「这次运行没有记录」。'
                    : '这次运行没有留下每步记录（多半不是由演示站发起的）。'}
                </p>
              )}
            </div>
            {d.replay.synthetic && (
              <p className="hint mt-10" data-src="backend">
                ⚠ {d.replay.note}
              </p>
            )}
          </section>

          {/* ===== 02 问文衡 · 问答与模型调用（票 06 块；契约 #30） ===== */}
          <AiRecords period={period} />

          {/* ===== 03 审计结论（失败优先：只露待确认/不通过，通过项折起） ===== */}
          <section className="card mt-18 pad-card">
            <h2 className="h-sec">
              审计结论
              <span className="hint">
                {d.audit.exists
                  ? `${auditRows.length} 项：${auditPass.length} 通过 · ${auditRows.filter((r) => r.status === 'review').length} 待确认 · ${auditRows.filter((r) => r.status === 'fail').length} 不通过`
                  : '未执行'}
              </span>
            </h2>
            {d.audit.exists ? (
              <>
                {auditBad.length ? (
                  <div className="tablewrap mt-10">
                    <table className="ar-tbl">
                      <thead>
                        <tr><th className="w-22p">审计项</th><th className="w-12p">判定</th>
                          <th className="w-26p">实测</th><th>说明</th></tr>
                      </thead>
                      <tbody>
                        {auditBad.map((it) => (
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
                ) : (
                  <p className="hint mt-8">全部通过。</p>
                )}
                {auditPass.length > 0 && (
                  <details className="fold mt-10">
                    <summary>已通过的 {auditPass.length} 项<span className="sm">点开看逐项实测</span></summary>
                    <div className="fold-inner">
                      <table className="ar-tbl">
                        <tbody>
                          {auditPass.map((it) => (
                            <tr key={it.id}>
                              <td><b>{it.title || it.id}</b></td>
                              <td className="mono">{it.metric || '—'}</td>
                              <td className="hint">{it.reason || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}
                {!!d.audit.truth_chain && d.audit.truth_chain !== '—' && (
                  <p className="hint mt-10">
                    真值链：{typeof d.audit.truth_chain === 'string' ? d.audit.truth_chain : '—'}
                  </p>
                )}
              </>
            ) : (
              <p className="hint mt-8">没有审计记录。</p>
            )}
          </section>

          {/* ===== 04 产物与日志包 ===== */}
          <section className="card mt-18 pad-card">
            <h2 className="h-sec">
              产物与日志包
              <span className="hint">日志包 {d.logpack.n_files} 个文件 · {humanSize(d.logpack.bytes)}</span>
            </h2>
            <div className="ar-arts">
              {!!d.logpack_url && (
                <a className="ar-art primary" href={d.logpack_url}>
                  <b>运行日志包（ZIP）</b>
                  <span className="m">{d.logpack.n_files} 个文件 · {humanSize(d.logpack.bytes)}</span>
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
          </section>

          {/* ===== 05 / 06 运行环境与指标（折叠，票 12） ===== */}
          <details className="fold">
            <summary>运行环境与指标<span className="sm">供排查与复现</span></summary>
            <div className="grid2 mt-0">
            <section className="card pad-card">
              <h2 className="h-sec">
                运行环境快照
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
            </section>

            <section className="card pad-card">
              <h2 className="h-sec">
                运行指标
              </h2>
              <dl className="ar-kv">
                <div><dt>当期 / 上期</dt><dd>{str(stats.period ?? d.period)} / {str(stats.prev)}</dd></div>
                <div><dt>数据校验</dt><dd>{stats.assertions_ok ? '全部通过' : `${str(stats.assertions_fail)} 处对不上`}</dd></div>
                <div><dt>预测 MAPE</dt><dd className="mono">{stats.predict_mape_overall == null ? '—' : `${stats.predict_mape_overall}%`}</dd></div>
                <div><dt>生成图表</dt><dd className="mono">{stats.charts == null ? '—' : `${stats.charts} 张`}</dd></div>
                <div><dt>全程耗时</dt><dd className="mono">{stats.elapsed_sec == null ? '—' : `${stats.elapsed_sec} 秒`}</dd></div>
              </dl>
            </section>
          </div>
          </details>

          {/* ===== 07 智能体轨迹文件（折叠收一句，票 12） ===== */}
          <details className="fold">
            <summary>智能体轨迹文件
              <span className="sm">{d.trace_files.length ? `${d.trace_files.length} / 3` : '本次没有轨迹'}</span>
            </summary>
            <div className="fold-inner">
              {d.trace_files.length ? (
                <div className="tablewrap">
                  <table className="ar-tbl">
                    <tbody>
                      {d.trace_files.map((n) => (
                        <tr key={n}><td className="mono">{n}</td><td className="hint">已归档</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="hint m-0">
                  本次没有轨迹文件。
                </p>
              )}
            </div>
          </details>
        </>
      )}
    </>
  )
}
