/* 生成台（工作台）——工具面。
   第一屏＝「这一期现在到哪一步、下一步做什么」；全屏只有一处朱色实心焦点。
   设计取自静态稿 mockups/v2-工作台与报告.html；状态与文案规格见 web/UX-生成台.md。 */

import type { ApiError, Me, Period, PeriodDetail } from './api'
import { useState } from 'react'
import { Icon } from './icons'
import { failureCopy, STATE_LABEL, type Workbench as WB, type WBState } from './wb'
import type { Run } from './App'

/** 五个模型的一句话说明（界面上"帮馆员选"的文案；预测台也用同一份，改一处两边一致） */
export const MODEL_DESC: Record<string, string> = {
  'Holt趋势模型': '只抓长期趋势、不管季节。适合稳定上升/下降的学科，外推最直接。',
  '阻尼Holt模型': '趋势会「减速」——越往前推越保守。适合增长在放缓的学科。',
  '季节性ETS模型': '抓「6 期一轮」的双月节律。适合受学年与发布节奏影响的指标。',
  'SARIMA模型': '趋势 + 季节都管，参数在最初 30 期按 AIC 选定后固定。通用、稳。',
  '经验贝叶斯状态空间模型': '把趋势与季节当「状态」逐期更新。对噪声大的序列更稳健。',
}
const MODELS = Object.keys(MODEL_DESC)

function Steps({ wb }: { wb: WB }) {
  return (
    <ol className="steplist">
      {wb.steps.map((s, i) => (
        <li key={s.key} className={`step ${s.on ? 'on' : ''} ${s.now ? 'now' : ''}`}>
          <span className="dot">{s.on ? <Icon name="check" size={13} /> : i + 1}</span>
          <span>
            {s.title}
            <small>{s.detail}</small>
          </span>
        </li>
      ))}
    </ol>
  )
}

function Progress() {
  const rows = [
    { name: '读取台账', pct: 100, state: 'done' },
    { name: '汇总数据', pct: 100, state: 'done' },
    { name: '预测与回看', pct: 100, state: 'done' },
    { name: '画图', pct: 69, state: 'now' },
    { name: '装配报告', pct: 0, state: 'wait' },
  ]
  return (
    <>
      <div className="elapsed">
        <Icon name="refresh" size={20} />
        正在生成 · 已用 8 秒
      </div>
      <div className="progress">
        {rows.map((r) => (
          <div key={r.name} className={`prow ${r.state === 'now' ? 'now' : ''}`}>
            <span style={{ flex: '0 0 22px', color: r.state === 'done' ? 'var(--ok)' : 'var(--ink-3)' }}>
              <Icon name={r.state === 'done' ? 'check' : r.state === 'now' ? 'refresh' : 'clock'} size={19} />
            </span>
            <span className="name">{r.name}</span>
            <span className="bar">
              <i style={{ width: `${r.pct}%` }} />
            </span>
            <span className="pct">
              {r.state === 'done' ? '完成' : r.state === 'now' ? `${r.pct}%` : '等待'}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}

/** 真实生成过程：后端推来的状态 + 最后一行进度 + 可展开的日志 */
function LiveRun({ run }: { run: Run }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <div className="elapsed">
        <Icon name="refresh" size={20} />
        {run.status ? `后端状态：${run.status}` : '正在生成……'}
      </div>
      <div className="progress">
        <div className="prow">
          <span className="name">最新进度</span>
          <span style={{ flex: 1, color: 'var(--ink-2)' }}>{run.last ?? '（等第一行进度…）'}</span>
        </div>
      </div>
      <div style={{ padding: '0 24px 16px' }}>
        <button className="btn" onClick={() => setOpen(!open)}>
          <Icon name="list" size={18} />{open ? '收起日志' : '看详细过程'}
        </button>
        {open && (
          <pre style={{
            marginTop: 10, maxHeight: 260, overflow: 'auto', background: 'var(--panel)',
            border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px',
            fontSize: 12.5, fontFamily: 'var(--mono)', color: 'var(--ink-2)',
          }}>
            {run.lines.length ? run.lines.join('\n') : '（暂无日志行）'}
          </pre>
        )}
      </div>
    </>
  )
}

function Banners({ wb, err, healthy, onRerun, period }: { wb: WB; err: ApiError | null; healthy: boolean; onRerun: () => void; period: string | null }) {
  if (wb.state === 'done' || wb.state === 'signed') {
    return (
      <div className="banner ok">
        <span className="ico"><Icon name="check" size={22} /></span>
        <span>
          <b className="title">{wb.state === 'signed' ? '本期已签发' : '本期报告已生成'}</b>
          <span>报告初稿与改动清单都在这期目录里；复核后在审核台签单。</span>
          <span className="acts">
            <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={19} />打开报告</a>
            <a className="btn" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={19} />去审核台</a>
          </span>
        </span>
      </div>
    )
  }
  if (wb.state === 'fail-ledger' || wb.state === 'fail-other' || wb.state === 'stalled') {
    const c = wb.state === 'stalled'
      ? { title: '看起来卡住了', lines: ['已有一段时间没有进展，可以取消重跑。', '上一版报告仍然有效。'] }
      : failureCopy(err, healthy)
    return (
      <>
        <div className="banner bad">
          <span className="ico"><Icon name="alert" size={22} /></span>
          <span>
            <b className="title">{c.title}</b>
            <ul>{c.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <span className="acts">
              <button className="btn" onClick={onRerun}><Icon name="refresh" size={19} />重新生成</button>
            </span>
          </span>
        </div>
        <div className="banner warn">
          <span className="ico"><Icon name="clock" size={22} /></span>
          <span><b className="title">上一版报告仍然有效</b>
            <span>本次失败没有动它；旧稿被隔离在 `_superseded/`，可追溯。</span></span>
        </div>
      </>
    )
  }
  return null
}

function ModelPicker() {
  return (
    <details className="model">
      <summary>
        <Icon name="arrow" size={19} />
        <span className="k">预测模型</span>
        <span className="v">用推荐（按学科，22 科已分别指定）</span>
      </summary>
      <div className="body">
        <p style={{ margin: '2px 0 12px', color: 'var(--ink-2)', fontSize: 15.5 }}>
          推荐值来自各学科历史数据的特征。想自己指定就逐科改选——每科下方是模型说明。
          <br />
          <span style={{ color: 'var(--ink-3)', fontSize: 14.5 }}>
            本次预测的是<b>被引</b>路线；另一条是排名路线，两条结论不一定一致，报告里会分别标注。
          </span>
        </p>
        <table>
          <thead>
            <tr><th>学科</th><th>推荐</th><th>我的选择</th></tr>
          </thead>
          <tbody>
            {[
              { d: '化学', rec: '季节性ETS模型' },
              { d: '工程学', rec: 'SARIMA模型' },
              { d: '材料科学', rec: '阻尼Holt模型' },
            ].map((row) => (
              <tr key={row.d}>
                <td>{row.d}</td>
                <td>{row.rec}</td>
                <td>
                  <select defaultValue={row.rec} aria-label={`${row.d}的预测模型`}>
                    {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <span className="mdesc">{MODEL_DESC[row.rec]}</span>
                </td>
              </tr>
            ))}
            <tr>
              <td colSpan={3} style={{ color: 'var(--ink-3)', fontSize: 14.5 }}>
                … 其余 19 个学科同理（本屏只列 3 科示意）
                <br />
                <span style={{ color: 'var(--gold-ink)' }}>
                  说明：模型清单与"推荐哪一科用哪个"目前还是前端占位——等契约 §2.2 #3 的接口。
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  )
}

export function Workbench({
  period, me, wb, err, healthy, run, onGenerate,
}: {
  period: string | null
  me: Me | null
  wb: WB
  err: ApiError | null
  healthy: boolean
  run?: Run | null
  onGenerate: () => void
}) {
  const canGenerate = me?.role === 'admin' && period != null

  return (
    <>
      <section className="card">
        <div className="steps">
          <h1>{period ?? '（选择期次）'}</h1>
          <span className="tag">{STATE_LABEL[wb.state]}</span>
          <Steps wb={wb} />
        </div>

        <div className="focus" style={{ margin: '0 24px 22px' }}>
          <div>
            <div className="big">{wb.focusTitle}</div>
            <div className="sub">{wb.focusSub}</div>
          </div>
          <div className="cta">
            {wb.focusAction === 'generate' && (
              <>
                <span className="hint">约 20 秒</span>
                <button className="btn primary" onClick={onGenerate} disabled={!canGenerate}>
                  <Icon name="play" size={20} />开始生成
                </button>
              </>
            )}
            {wb.focusAction === 'rerun' && (
              <button className="btn" onClick={onGenerate} disabled={!canGenerate}>
                <Icon name="refresh" size={20} />重新生成
              </button>
            )}
            {wb.focusAction === 'sign' && (
              <a className="btn primary" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={20} />复核并签单</a>
            )}
            {wb.focusAction === 'open' && (
              <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={20} />打开报告</a>
            )}
          </div>
        </div>

        {!canGenerate && (
          <p className="hint" style={{ padding: '0 24px 18px' }}>
            {me == null
              ? <>角色<b>未知</b>（后端未提供 /api/me，契约 §2.2 的 P0 #1）——为安全起见，生成按钮先禁用。
                  这不是「你是游客」，只是前端<b>不知道</b>你是谁。</>
              : me.role === 'admin'
                ? <>生成按钮暂不可用：还没有选中期次。</>
                : <>当前账号是<b>游客</b>：只能看报告目录与成品，不能生成或编辑。</>}
          </p>
        )}

        {run ? <LiveRun run={run} /> : wb.state === 'running' ? <Progress /> : null}
        <Banners wb={wb} err={err} healthy={healthy} onRerun={onGenerate} period={period} />

        {wb.note && (
          <div style={{ padding: '0 24px 20px' }}>
            <div className="degraded">{wb.note}</div>
          </div>
        )}
      </section>

      <ModelPicker />
    </>
  )
}

export type { WBState, Period, PeriodDetail }
