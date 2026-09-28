import { useEffect, useRef, useState } from 'react'
import { loadShelfPreviews } from './data'
import { libraryAudio } from './library-audio'
import LibraryExperience, { type ExperienceStage } from './LibraryExperience'
import LibraryHome from './LibraryHome'
import Reader, { type ReaderSection } from './Reader'
import type { ShelfLoadResult } from './types'
import './library.css'

type PageState =
  | { kind: 'loading' }
  | ShelfLoadResult

type Stage = 'home' | ExperienceStage | 'reader'
type ReaderReturnTo = 'home' | 'room'

export default function ShelfPage() {
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [stage, setStage] = useState<Stage>('home')
  const [activeReader, setActiveReader] = useState<{ bookIndex: number; section: ReaderSection } | null>(null)
  const [readerReturnTo, setReaderReturnTo] = useState<ReaderReturnTo>('home')
  const [attempt, setAttempt] = useState(0)
  const [motion, setMotion] = useState(true)
  const [soundEnabled, setSoundEnabled] = useState(() => libraryAudio.isEnabled())
  const [view, setView] = useState<'front' | 'aerial'>('front')
  const [returnIssue, setReturnIssue] = useState<number | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const enterTimeoutRef = useRef<number | null>(null)

  useEffect(() => {
    setMotion(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  }, [])

  useEffect(() => {
    if (state.kind !== 'guest') return

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

  useEffect(() => () => {
    if (enterTimeoutRef.current !== null) window.clearTimeout(enterTimeoutRef.current)
  }, [])

  function retry() {
    setAttempt((current) => current + 1)
  }

  function toggleSound() {
    setSoundEnabled(libraryAudio.toggle())
  }

  function enterExterior() {
    if (enterTimeoutRef.current !== null) window.clearTimeout(enterTimeoutRef.current)
    enterTimeoutRef.current = null
    if (soundEnabled) libraryAudio.arm()
    setReturnIssue(null)
    setStage('exterior')
  }

  function enterRoom() {
    if (stage !== 'exterior') return
    setStage('entering')
    enterTimeoutRef.current = window.setTimeout(() => {
      enterTimeoutRef.current = null
      setStage('room')
    }, motion ? 1100 : 100)
  }

  function returnHome() {
    if (enterTimeoutRef.current !== null) window.clearTimeout(enterTimeoutRef.current)
    enterTimeoutRef.current = null
    setReturnIssue(null)
    setStage('home')
  }

  function openReader(bookIndex: number, section: ReaderSection, returnTo: ReaderReturnTo, trigger?: HTMLButtonElement) {
    if (state.kind !== 'guest' || !state.books[bookIndex]) return
    returnFocusRef.current = trigger
      ?? document.querySelector<HTMLElement>('.room-catalog-list summary')
      ?? document.querySelector<HTMLElement>('.room-heading h1')
    setReaderReturnTo(returnTo)
    setReturnIssue(bookIndex)
    setActiveReader({ bookIndex, section })
    setStage('reader')
  }

  function closeReader() {
    if (!activeReader) return
    const { bookIndex } = activeReader
    setActiveReader(null)
    if (readerReturnTo === 'room' && motion) {
      setReturnIssue(bookIndex)
      setStage('returning')
      return
    }
    setReturnIssue(null)
    setStage(readerReturnTo)
  }

  function finishReturn() {
    setReturnIssue(null)
    setStage('room')
  }

  function switchReaderBook(index: number) {
    setActiveReader((current) => {
      if (!current || state.kind !== 'guest' || !state.books[index]) return current
      return { ...current, bookIndex: index }
    })
  }

  if (state.kind === 'loading') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <p className="library-status" role="status" aria-live="polite">正在确认身份并读取馆藏预览……</p>
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
            <p>登录后才能查看已开放的馆藏预览。</p>
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
            <h1>暂时无法打开预览</h1>
            <p>当前账号无法查看这份馆藏预览。</p>
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
            <h1>馆藏预览暂不可用</h1>
            <p>{state.kind === 'invalid-data'
              ? '目前读到的内容不符合预览范围，因此没有显示。'
              : '现在无法确认身份或读取馆藏预览，请稍后重试。'}</p>
            <button className="library-action" type="button" onClick={retry}>再试一次</button>
          </section>
        </div>
      </main>
    )
  }

  const activeBook = activeReader ? state.books[activeReader.bookIndex] : undefined
  const showHome = stage === 'home' || (stage === 'reader' && readerReturnTo === 'home')
  const showExperience = stage !== 'home' && (stage !== 'reader' || readerReturnTo === 'room')
  const experienceStage: ExperienceStage = stage === 'home' || stage === 'reader' ? 'room' : stage

  return <>
    {showHome && <div hidden={stage !== 'home'}>
      <LibraryHome
        books={state.books}
        onEnterExterior={enterExterior}
        onOpenBook={(bookIndex, section, trigger) => openReader(bookIndex, section, 'home', trigger)}
      />
    </div>}

    {showExperience && <div hidden={stage === 'reader'}>
      <LibraryExperience
        books={state.books}
        stage={experienceStage}
        motion={motion}
        soundEnabled={soundEnabled}
        view={view}
        returnIssue={returnIssue}
        onMotionChange={setMotion}
        onSoundToggle={toggleSound}
        onViewChange={setView}
        onEnterRoom={enterRoom}
        onBackHome={returnHome}
        onPickBook={(bookIndex) => openReader(bookIndex, 'cover', 'room')}
        onTakeStart={() => libraryAudio.playPull()}
        onReturnComplete={finishReturn}
        onOpenPreview={(bookIndex, trigger) => openReader(bookIndex, 'cover', 'room', trigger)}
      />
    </div>}

    {stage === 'reader' && activeBook && activeReader && <Reader
      key={`${activeReader.bookIndex}-${activeReader.section}`}
      books={state.books}
      bookIndex={activeReader.bookIndex}
      initialSection={activeReader.section}
      motion={motion}
      soundEnabled={soundEnabled}
      onMotionChange={setMotion}
      onSoundToggle={toggleSound}
      onBackHome={returnHome}
      onSelectBook={switchReaderBook}
      onClose={closeReader}
    />}
  </>
}
