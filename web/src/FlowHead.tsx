/* 出报告四步的公共页头（2026-11-05 rick 定）：
   顶部步骤条已经标出「你在第几步」，页头就不再重复写页名——只留
   「本期 + 期号 + 数据截至」一行，右端放这一屏自己的动作。
   四屏（取数核验 / 预测选模 / 生成初稿 / 核验定稿）共用这一个组件，尺寸一致。 */

import type { ReactNode } from 'react'
import type { PeriodDetail } from './api'

export function FlowHead({
  period, issue, detail, right, hint,
}: {
  period: string | null
  /** 总期号（如「第 39 期」）；由调用方从期次列表的 label 里取，取不到就不写 */
  issue?: string
  /** 期次事实（数据窗口）；还没读到时留空，不编 */
  detail: PeriodDetail | null
  /** 这一屏自己的动作（回报告 / 开新一期 / 保存……） */
  right?: ReactNode
  /** 紧贴现次说明的一小块（状态签 / ⓘ 口径），只放事实，不放解释 */
  hint?: ReactNode
}) {
  return (
    <div className="flow-head">
      <h1 className="fh-period">本期 {period ?? '——————'}</h1>
      <span className="fh-sub">
        {issue || '期次待定'}
        {detail?.window ? ` · 数据截至 ${detail.window}` : ''}
      </span>
      {hint && <span className="fh-hint">{hint}</span>}
      {right && <div className="fh-acts">{right}</div>}
    </div>
  )
}

export type FlowTocTone = 'ok' | 'wait' | 'warn' | 'now'

/** 页内分节的一行：章号 + 名称 + 点线 + 右端状态（论文目录的排法） */
export function FlowToc({ rows, label }: {
  rows: { no: string; name: string; status: string; tone?: FlowTocTone }[]
  label?: string
}) {
  return (
    <ol className="flow-toc" aria-label={label}>
      {rows.map((row) => (
        <li key={row.no + row.name} className={row.tone ?? 'ok'}>
          <span className="num" aria-hidden="true">{row.no}</span>
          <span className="name">{row.name}</span>
          <span className="lead" aria-hidden="true" />
          <span className="st"><i className="mk" aria-hidden="true" />{row.status}</span>
        </li>
      ))}
    </ol>
  )
}
