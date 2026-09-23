/* 报告 · 数据视图（取自静态稿 mockups/v2-工作台与报告.html 的报告屏）
   与 G 的翻书**分工**：翻书＝读正文（人的阅读）；这里＝看数据与改动（大表 / 朱批 / 溯源 / 印记链）。

   🔴 诚实边界（项目红线：缺数据不填假数）：
     今天能拿真数据的只有三样——**期次、印记链（签单状态）、产物列表**。
     读数带 / 页边朱批 / 大表 / 溯源 都要等契约 §2.2 的接口；就绪前整块写明"等什么"，
     不放占位数字、不假装有内容。
*/

import { useEffect, useState } from 'react'
import {
  getArtifacts, getStatus, humanSize,
  type Artifact, type Period,
} from './api'
import { Icon } from './icons'

/** 期次印记链：签过＝朱印 / 签名失效＝金印 / 未签发＝墨线框。这是产品的原创资产，也是本屏的记忆点。 */
function Chain({
  periods, current, onPick,
}: {
  periods: Period[]
  current: string | null
  onPick: (p: string) => void
}) {
  return (
    <aside className="chain">
      <h3>期次印记链</h3>
      <p className="cap">
        按时间从左到右。签过是朱印，签名失效是金印，未签发是墨线框。
        <br />
        （期号与月份来自后端；点一枚换一期。）
      </p>
      <div className="seals">
        {periods.map((p) => {
          const cls = p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'
          const isNow = p.period === current
          return (
            <button
              key={p.period}
              type="button"
              className="sealbox"
              onClick={() => onPick(p.period)}
              style={{ background: 'none', border: 0, cursor: 'pointer', padding: 0 }}
              aria-current={isNow}
            >
              <span className="now-tag">{isNow ? '本期' : ''}</span>
              <span className={`seal ${cls} ${isNow ? 'now' : ''}`}>{p.period}</span>
              <span className="lbl">{p.label}</span>
            </button>
          )
        })}
      </div>
      <div className="legend">
        <span><i style={{ background: 'var(--zhu)' }} />已签发</span>
        <span><i style={{ boxShadow: 'inset 0 0 0 2px var(--gold)' }} />签名失效</span>
        <span><i style={{ boxShadow: 'inset 0 0 0 2px var(--line)' }} />未签发</span>
      </div>
    </aside>
  )
}

/** 产物卡：真数据（/api/status 取最近一次任务 → /api/jobs/{id}/artifacts） */
function Artifacts() {
  const [items, setItems] = useState<Artifact[] | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const st = await getStatus()
        const id = st.last?.id
        if (!id) {
          if (alive) setNote('还没有任何一次生成记录。')
          return
        }
        const list = await getArtifacts(id)
        if (alive) setItems(list)
      } catch (e) {
        const h = e as { status?: number }
        if (!alive) return
        setNote(
          h.status === 403
            ? '产物清单需要管理员权限（后端按角色拦的，不是前端藏起来的）。'
            : h.status === 401
              ? '需要登录才能看产物清单。'
              : '读产物清单失败。',
        )
      }
    })()
    return () => { alive = false }
  }, [])

  if (note) return <div className="pending-box">{note}</div>
  if (!items) return <div className="pending-box">正在读产物清单……</div>

  return (
    <div className="artifacts">
      {items.map((a) => (
        <div className="art" key={a.key}>
          <span className="ico"><Icon name={a.key === 'report' ? 'doc' : a.key.includes('red') ? 'list' : 'chart'} size={22} /></span>
          <span>
            <span className="n">{a.label}</span>
            <span className="m">
              {a.name}
              {a.size != null ? ` · ${humanSize(a.size)}` : ''}
            </span>
          </span>
          <span className="go"><a href={a.url} target="_blank" rel="noreferrer">打开</a></span>
        </div>
      ))}
    </div>
  )
}

export function Report({
  periods, current, onPick,
}: {
  periods: Period[]
  current: string | null
  onPick: (p: string) => void
}) {
  const row = periods.find((p) => p.period === current) ?? null

  return (
    <>
      <div className="report-head">
        <div>
          <div className="eyebrow">学科信息参考 · ESI 双月报告</div>
          <h1 className="display">
            {row?.label ?? '（选择期次）'}
            <small>
              目录名 {current ?? '—'} · 数据源与覆盖窗口等待接口（见下方说明）
            </small>
          </h1>
          <div className="rule" />

          {/* 读数带：等契约 §2.2 #2（单期详情） */}
          <div className="readouts">
            {['国际排名', '顶尖论文', '覆盖学科', '图表'].map((k) => (
              <div className="readout" key={k}>
                <div className="k">{k}</div>
                <div className="v pending">待接口</div>
                <div className="d" style={{ color: 'var(--ink-3)' }}>不填假数</div>
              </div>
            ))}
          </div>
          <div className="pending-box">
            <b>这一屏还差什么（前端已就位，等后端）</b>
            <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              <li><code>GET /api/periods/&#123;期次&#125;</code> → 覆盖窗口、期号/总期号、卷色、三步状态（契约 §2.2 #2）</li>
              <li><code>GET /api/periods/&#123;期次&#125;/redslots</code> → 页边朱批与"本期改动"（§2.2 #4）</li>
              <li><code>GET /api/periods/&#123;期次&#125;/collation</code> → 大表与逐格溯源（§2.2 #5）</li>
              <li><code>GET /api/periods/&#123;期次&#125;/charts</code> → 图册（§2.2 #6）</li>
            </ul>
            <div style={{ marginTop: 8 }}>
              接口一到，这一屏就自动长出读数带、朱批与大表——<b>不需要前端再改结构</b>。
            </div>
          </div>
        </div>

        {/* 印记链：今天就有真数据 */}
        <Chain periods={periods} current={current} onPick={onPick} />
      </div>

      <section className="card" style={{ marginTop: 26, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="doc" size={21} />本期产物
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            （真数据：来自最近一次生成任务的产物清单）
          </span>
        </h2>
        <Artifacts />
      </section>
    </>
  )
}
