import { useEffect, useRef, useState } from 'react'
import { loadShelfPreviews } from './data'
import Reader, { type ReaderSection } from './Reader'
import ShelfScene from './scene/ShelfScene'
import type { ShelfLoadResult } from './types'
import './library.css'

type PageState =
  | { kind: 'loading' }
  | Exclude<ShelfLoadResult, { kind: 'admin' }>

export default function ShelfPage() {
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [activeReader, setActiveReader] = useState<{ bookIndex: number; section: ReaderSection } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const returnFocusRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    void loadShelfPreviews(controller.signal).then((result) => {
      if (controller.signal.aborted) return
      if (result.kind === 'admin') {
        window.location.replace('/app/')
        return
      }
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

  if (state.books.length === 0) {
    return (
      <main className="library-page">
        <div className="library-shell">
          <LibraryHeading />
          <section className="library-message" role="status">
            <h2>目前没有可预览的馆藏</h2>
            <p>目前没有可查阅的封面、目录或名词解释。</p>
          </section>
        </div>
      </main>
    )
  }

  const activeBook = activeReader ? state.books[activeReader.bookIndex] : undefined

  return (
    <main className="library-page">
      <div className="library-shell">
        <div className="library-shelf-view" hidden={Boolean(activeReader && activeBook)}>
          <LibraryHeading />
          <ShelfScene
            books={state.books}
            onOpen={(bookIndex, section, trigger) => {
              returnFocusRef.current = trigger
              setActiveReader({ bookIndex, section })
            }}
          />
          <p className="library-footnote">此处只展示封面、目录和名词解释。</p>
        </div>
        {activeReader && activeBook && (
          <Reader
            key={`${activeReader.bookIndex}-${activeReader.section}`}
            book={activeBook}
            initialSection={activeReader.section}
            onClose={() => setActiveReader(null)}
          />
        )}
      </div>
    </main>
  )
}

function LibraryHeading() {
  return (
    <header className="library-heading">
      <p className="library-eyebrow">文衡 · 馆藏预览</p>
      <h1>学科信息参考</h1>
      <p>可查阅开放期次的封面、目录和名词解释。</p>
    </header>
  )
}
