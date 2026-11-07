/* 全站统一的身份控件（2026-10-12 rick 定）：头像 + 名字。
   2026-11-07 rick 定（按图一复刻）：收编右上簇——ⓘ 口径声明与 ⚙ 设置钮撤出行，
   点身份行弹出用户菜单：设置（Ctrl+,）／意见反馈／口径与声明／退出登录＋底部身份行。
   三页（工作区 / 问文衡 / 高校ESI）同一组件、同一交互。 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Icon } from '../icons'
import type { Me } from '../api'

export function UserChip({ me, dock, onSettings, onFeedback, info }: {
  me: Me | null
  dock?: boolean
  /** 设置中心入口（useSettingsCenter 的 show；Ctrl+, 全局快捷键不受影响） */
  onSettings?: () => void
  /** 意见反馈入口（SideRail 自持反馈对话框） */
  onFeedback?: () => void
  /** 口径与声明（全站唯一一份，SideRail 传入——声明内容一字不改） */
  info?: ReactNode
}) {
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

  const close = () => setOpen(false)

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
              title={`${me.name} · ${role}——点这里：设置 / 意见反馈 / 口径声明 / 退出`}
              onClick={() => setOpen((v) => !v)}>
        <span className="av">{me.name.slice(0, 1)}</span>
        <span className="user-chip-name">{me.name}</span>
      </button>
      {open && (
        <span className="user-chip-pop user-menu" role="menu" aria-label="用户菜单">
          <button type="button" role="menuitem" className="um-item"
                  onClick={() => { close(); onSettings?.() }}>
            <Icon name="gear" size={16} />
            <span className="um-lbl">设置</span>
            <kbd className="um-kbd">Ctrl + ,</kbd>
          </button>
          <button type="button" role="menuitem" className="um-item"
                  onClick={() => { close(); onFeedback?.() }}>
            <Icon name="mail" size={16} />
            <span className="um-lbl">意见反馈</span>
          </button>
          {info && (
            <details className="um-item um-info">
              <summary role="menuitem" className="um-row" title="口径、来源与只读声明">
                <Icon name="seal" size={16} />
                <span className="um-lbl">口径与声明</span>
              </summary>
              <div className="um-info-body">{info}</div>
            </details>
          )}
          <span className="um-sep" aria-hidden="true" />
          <a role="menuitem" className="um-item" href="/logout" onClick={() => close()}>
            <Icon name="signout" size={16} />
            <span className="um-lbl">退出登录</span>
          </a>
          <div className="um-id">
            <span className="av" aria-hidden="true">{me.name.slice(0, 1)}</span>
            <div className="um-id-txt">
              <b>{me.name}</b>
              <span>{role}</span>
            </div>
          </div>
        </span>
      )}
    </span>
  )
}
