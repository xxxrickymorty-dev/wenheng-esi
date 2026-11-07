/* 意见反馈对话框（2026-11-07 用户菜单收编件）：馆员/评委写一句 → POST /api/feedback。
   服务端落在 wenheng/_feedback/feedback.jsonl（out/ 数据红线之外）；
   无后端改动的老部署提交会得到 404，对话框如实报「反馈通道未开通」。 */
import { useEffect, useRef, useState } from 'react'

type Phase = 'idle' | 'sending' | 'ok' | 'err'

export function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [note, setNote] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const submit = async () => {
    if (!text.trim() || phase === 'sending') return
    setPhase('sending')
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.trim() }),
      })
      if (res.ok) {
        setPhase('ok')
        setNote('')
        setText('')
        window.setTimeout(onClose, 900)
      } else {
        const body = await res.json().catch(() => null)
        setPhase('err')
        setNote(body?.hint || body?.error || `提交失败（${res.status}）`)
      }
    } catch {
      setPhase('err')
      setNote('网络不通——稍后再试')
    }
  }

  return (
    <div className="fb-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="fb-panel" role="dialog" aria-modal="true" aria-label="意见反馈" ref={boxRef}>
        <header className="fb-head">
          <b>意见反馈</b>
          <button type="button" className="fb-x" onClick={onClose} aria-label="关闭">×</button>
        </header>
        {phase === 'ok' ? (
          <p className="fb-ok">已收到，谢谢——这条会进馆内反馈记录。</p>
        ) : (
          <>
            <textarea className="fb-text" value={text} rows={5} maxLength={2000}
                      placeholder="写一句：哪一步看不懂、想导出的表没有、口径有疑问……"
                      onChange={(e) => { setText(e.target.value); if (phase === 'err') setPhase('idle') }} />
            {phase === 'err' && <p className="fb-err" role="alert">{note}</p>}
            <div className="fb-acts">
              <span className="fb-hint">{text.length}/2000</span>
              <button type="button" className="fb-send" disabled={!text.trim() || phase === 'sending'}
                      onClick={submit}>
                {phase === 'sending' ? '提交中…' : '提 交'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
