/* ⓘ 口径弹层（票 13 起用）：点开就地看「这段数/这个词指什么」。
   用原生 details/summary——零脚本、键盘可达；正文折叠里也照常工作。 */

import type { ReactNode } from 'react'

export function Info({ label, children, end }: {
  /** 无障碍与悬停用的说明名，如「期次与数据说明」 */
  label: string
  children: ReactNode
  /** 贴右对齐（放在行尾时用，弹层不出框） */
  end?: boolean
}) {
  return (
    <details className={`info${end ? ' end' : ''}`}>
      <summary title={label} aria-label={label}>ⓘ</summary>
      <div className="info-body" role="note">{children}</div>
    </details>
  )
}
