import { useEffect, useState } from 'react'
import { loadShelfPreviews } from './data'
import type { ShelfBookPreview, ShelfLoadResult } from './types'
import './library.css'

type PageState =
  | { kind: 'loading' }
  | Exclude<ShelfLoadResult, { kind: 'admin' }>

function bookLabel(book: ShelfBookPreview): string {
  return book.cover[2]?.trim() || book.cover[1]?.trim() || '查看封面'
}

export default function ShelfPage() {
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    void loadShelfPreviews(controller.signal).then((result) => {
      if (controller.signal.aborted) return
      if (result.kind === 'admin') {
        window.location.replace('/app/')
        return
      }
      setSelectedIndex(0)
      setState(result)
    }).catch(() => {
      if (!controller.signal.aborted) setState({ kind: 'unavailable' })
    })

    return () => controller.abort()
  }, [attempt])

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

  const selectedBook = state.books[selectedIndex] ?? state.books[0]

  return (
    <main className="library-page">
      <div className="library-shell">
        <LibraryHeading />
        <div className="library-layout">
          <nav className="library-periods" aria-label="选择可预览期次">
            <h2>可预览期次</h2>
            <ul>
              {state.books.map((book, index) => (
                <li key={index}>
                  <button
                    className="library-period-button"
                    type="button"
                    aria-pressed={selectedIndex === index}
                    onClick={() => setSelectedIndex(index)}
                  >
                    <span>{bookLabel(book)}</span>
                    <span className="library-period-hint">打开预览</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <article className="library-preview" aria-label="馆藏安全预览">
            <section className="library-cover" aria-labelledby="library-cover-title">
              <p className="library-eyebrow">封面</p>
              <h2 id="library-cover-title">{selectedBook.cover[1]}</h2>
              <div className="library-cover-lines">
                {selectedBook.cover.filter((line) => line.trim().length > 0).map((line, index) => (
                  <p key={`${index}-${line}`}>{line}</p>
                ))}
              </div>
            </section>

            <section className="library-section" aria-labelledby="library-toc-title">
              <p className="library-eyebrow">目录</p>
              <h2 id="library-toc-title">报告章节</h2>
              <ol className="library-toc">
                {selectedBook.toc.map((entry, index) => (
                  <li key={`${index}-${entry.title}`}>
                    <span>{entry.title}</span>
                  </li>
                ))}
              </ol>
            </section>

            <section className="library-section" aria-labelledby="library-glossary-title">
              <p className="library-eyebrow">名词解释</p>
              <h2 id="library-glossary-title">报告中的用语</h2>
              <dl className="library-glossary">
                {selectedBook.glossary.map((entry, index) => (
                  <div className="library-glossary-entry" key={`${index}-${entry.term}`}>
                    <dt>{entry.term}</dt>
                    <dd>{entry.definition}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </article>
        </div>
        <p className="library-footnote">此处只展示封面、目录和名词解释。</p>
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
