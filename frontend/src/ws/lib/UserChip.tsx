/* 全站统一的身份控件（2026-10-12 rick 定）：头像 + 「名字 · 角色」；
   不摆显眼退出按钮——点击才弹出「退出登录」；两页（工作区 / 对话页）同一组件、同一交互。 */
import { useEffect, useRef, useState } from 'react'
import type { Me } from '../api'

export function UserChip({ me, dock = false }: { me: Me | null; dock?: boolean }) {
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

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
  return (
    <span className={`user-chip${dock ? ' user-chip-dock' : ''}`} ref={boxRef}>
      <button type="button" className="user-chip-btn" aria-haspopup="menu" aria-expanded={open}
              title={`${me.name} · ${role}——点这里可退出登录`}
              onClick={() => setOpen((v) => !v)}>
        <span className="av">{me.name.slice(0, 1)}</span>
        <span className="user-chip-name">{me.name} · {role}</span>
      </button>
      {open && (
        <span className="user-chip-pop" role="menu">
          <a role="menuitem" href="/logout">退出登录</a>
        </span>
      )}
    </span>
  )
}
