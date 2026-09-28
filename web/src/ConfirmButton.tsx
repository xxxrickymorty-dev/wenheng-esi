/* 行内二次确认按钮（票 06；UX.md 第十节：危险动作先确认、行内、3 秒归还）。
   第一次点 = 进入确认态（按钮文案换成 confirmText，3 秒后自动还原）；
   第二次点 = 真正执行。不改按钮原有样式类，确认态加 .confirming。
   禁用态照原样透传；键盘 Enter/Space 与鼠标等价（都是 click）。 */

import { useEffect, useRef, useState, type ReactNode } from 'react'

export function ConfirmButton({
  className = 'btn', confirmText = '确认执行？', title, disabled, onConfirm, children,
}: {
  className?: string
  confirmText?: string
  title?: string
  disabled?: boolean
  onConfirm: () => void
  children: ReactNode
}) {
  const [armed, setArmed] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => { if (timer.current !== undefined) window.clearTimeout(timer.current) }, [])

  function disarm() {
    if (timer.current !== undefined) window.clearTimeout(timer.current)
    timer.current = undefined
    setArmed(false)
  }

  return (
    <button
      type="button"
      className={`${className}${armed ? ' confirming' : ''}`}
      disabled={disabled}
      title={title}
      data-armed={armed || undefined}
      onClick={() => {
        if (armed) { disarm(); onConfirm(); return }
        setArmed(true)
        timer.current = window.setTimeout(() => setArmed(false), 3000)
      }}
    >
      {armed ? confirmText : children}
    </button>
  )
}
