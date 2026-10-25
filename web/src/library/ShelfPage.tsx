import { useEffect, useRef, useState } from 'react'
import { loadShelfPreviews } from './data'
import { libraryAudio } from './library-audio'
import LibraryHome from './LibraryHome'
import Reader, { type ReaderSection } from './Reader'
import type { ShelfLoadResult } from './types'
import './library.css'

type PageState =
  | { kind: 'loading' }
  | ShelfLoadResult

type Stage = 'home' | 'reader'
type ReaderReturnTo = 'home'

export default function ShelfPage() {
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [stage, setStage] = useState<Stage>('home')
  const [activeReader, setActiveReader] = useState<{ bookIndex: number; section: ReaderSection } | null>(null)
  const [readerReturnTo, setReaderReturnTo] = useState<ReaderReturnTo>('home')
  const [attempt, setAttempt] = useState(0)
  const [motion, setMotion] = useState(true)
  const [soundEnabled, setSoundEnabled] = useState(() => libraryAudio.isEnabled())
  const returnFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    setMotion(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  }, [])

  useEffect(() => {
    if (state.kind !== 'preview' && state.kind !== 'full') return

    const onVisibility = () => libraryAudio.handleVisibility(document.hidden)
    const armAudio = () => libraryAudio.arm()

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pointerdown', armAudio, { capture: true, once: true })
    window.addEventListener('keydown', armAudio, { capture: true, once: true })

    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pointerdown', armAudio, true)
      window.removeEventListener('keydown', armAudio, true)
    }
  }, [state.kind])

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    void loadShelfPreviews(controller.signal).then((result) => {
      if (controller.signal.aborted) return
      setState(result)
    }).catch(() => {
      if (!controller.signal.aborted) setState({ kind: 'unavailable' })
    })

    return () => controller.abort()
  }, [attempt])

  useEffect(() => {
    if (!activeReader && returnFocusRef.current) {
      returnFocusRef.current.focus()
      returnFocusRef.current = null
    }
  }, [activeReader])

  function retry() {
    setAttempt((current) => current + 1)
  }

  function toggleSound() {
    setSoundEnabled(libraryAudio.toggle())
  }

  function openReader(bookIndex: number, section: ReaderSection, returnTo: ReaderReturnTo, trigger?: HTMLButtonElement) {
    if ((state.kind !== 'preview' && state.kind !== 'full') || !state.books[bookIndex]) return
    returnFocusRef.current = trigger ?? null
    setReaderReturnTo(returnTo)
    setActiveReader({ bookIndex, section })
    setStage('reader')
  }

  function closeReader() {
    if (!activeReader) return
    setActiveReader(null)
    setStage(readerReturnTo)
  }

  if (state.kind === 'loading') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <p className="library-status" role="status" aria-live="polite">正在确认身份并调取馆藏……</p>
        </div>
      </main>
    )
  }

  if (state.kind === 'login') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>请先登录</h1>
            <p>登录后才能阅览馆藏全内容。</p>
            <a className="library-action" href="/login">前往登录</a>
          </section>
        </div>
      </main>
    )
  }

  if (state.kind === 'forbidden') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>暂时无法打开馆藏</h1>
            <p>当前账号无法查看这份馆藏内容。</p>
            <button className="library-action" type="button" onClick={retry}>再试一次</button>
          </section>
        </div>
      </main>
    )
  }

  if (state.kind === 'unavailable' || state.kind === 'invalid-data') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>馆藏暂不可用</h1>
            <p>{state.kind === 'invalid-data'
              ? '目前读到的内容不符合可阅览范围，因此没有显示。'
              : '现在无法确认身份或读取馆藏内容，请稍后重试。'}</p>
            <button className="library-action" type="button" onClick={retry}>再试一次</button>
          </section>
        </div>
      </main>
    )
  }

  const activeBook = activeReader ? state.books[activeReader.bookIndex] : undefined

  return <>
    {/* 阅览期间首页隐藏但不卸载：归架后焦点能落回原来那枚书封按钮 */}
    <div hidden={stage !== 'home'}>
      <LibraryHome
        books={state.books}
        backToWorkspace={state.kind === 'full'}
        onOpenBook={(bookIndex, section, trigger) => openReader(bookIndex, section, 'home', trigger)}
      />
    </div>

    {stage === 'reader' && activeBook && activeReader && <Reader
      key={`${activeReader.bookIndex}-${activeReader.section}`}
      books={state.books}
      bookIndex={activeReader.bookIndex}
      initialSection={activeReader.section}
      motion={motion}
      soundEnabled={soundEnabled}
      onMotionChange={setMotion}
      onSoundToggle={toggleSound}
      onBackHome={closeReader}
      onClose={closeReader}
    />}
  </>
}
