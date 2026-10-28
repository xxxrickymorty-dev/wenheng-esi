/* 全站统一的身份控件（2026-10-12 rick 定）：头像 + 「名字 · 角色」；
   不摆显眼退出按钮——点击才弹出「退出登录」；两页（工作区 / 对话页）同一组件、同一交互。
   float（2026-10-28）：左栏里的浮层改「浮出左栏」——fixed 锚定左栏右缘、
   portal 到 body（page-l 是 sticky，自带 stacking context，
   困在栏里的 fixed 会被右页 .wrap 盖住——诊断实测）；左栏内容不再被盖。 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Me } from '../api'

export function UserChip({ me, dock = false, float = false }: { me: Me | null; dock?: boolean; float?: boolean }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const boxRef = useRef<HTMLSpanElement>(null)
  const popRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      const t = event.target as Node
      if (boxRef.current?.contains(t) || popRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = () => {
    if (!open && float && boxRef.current) {
      /* 锚定左栏右缘（不是签右缘）：左栏窄时签几乎撑满，
         以签定位仍会压栏——落点统一在栏缘外 10px */
      const pl = boxRef.current.closest('.page-l')
      const r = boxRef.current.getBoundingClientRect()
      setAnchor({ x: (pl?.getBoundingClientRect().right ?? r.right + 12) + 10, y: r.top })
    }
    setOpen((v) => !v)
  }

  if (!me) {
    return (
      <span className={`user-chip${dock ? ' user-chip-dock' : ''}`} aria-live="polite">
        <span className="user-chip-btn" aria-disabled="true">
          <span className="av">？</span><span className="user-chip-name">角色确认中…</span>
        </span>
      </span>
    )
  }

  const role = me.role === 'admin' ? '管理员' : '操作员'
  const pop = (
    <span className="user-chip-pop" role="menu" ref={float ? popRef : undefined}
          style={float && anchor ? { position: 'fixed', left: anchor.x, top: anchor.y } : undefined}>
      <a role="menuitem" href="/logout">退出登录</a>
    </span>
  )
  return (
    <span className={`user-chip${dock ? ' user-chip-dock' : ''}`} ref={boxRef}>
      <button type="button" className="user-chip-btn" aria-haspopup="menu" aria-expanded={open}
              title={`${me.name} · ${role}——点这里可退出登录`}
              onClick={toggle}>
        <span className="av">{me.name.slice(0, 1)}</span>
        <span className="user-chip-name">{me.name} · {role}</span>
      </button>
      {open && (float && anchor ? createPortal(pop, document.body) : pop)}
    </span>
  )
}
