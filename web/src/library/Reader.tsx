import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { ShelfBookPreview } from './types'

export type ReaderSection = 'cover' | 'toc' | 'glossary'

type ReaderProps = {
  book: ShelfBookPreview
  initialSection: ReaderSection
  onClose: () => void
}

const sections: { id: ReaderSection; label: string }[] = [
  { id: 'cover', label: '封面' },
  { id: 'toc', label: '目录' },
  { id: 'glossary', label: '名词解释' },
]

export default function Reader({ book, initialSection, onClose }: ReaderProps) {
  const [activeSection, setActiveSection] = useState(initialSection)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  function selectSection(index: number, moveFocus: boolean) {
    const nextIndex = (index + sections.length) % sections.length
    setActiveSection(sections[nextIndex].id)
    if (moveFocus) {
      window.requestAnimationFrame(() => tabRefs.current[nextIndex]?.focus())
    }
  }

  function handleReaderKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape' || event.altKey || event.ctrlKey || event.metaKey
      || event.nativeEvent.isComposing) return
    event.preventDefault()
    onClose()
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) return

    const focusedIndex = tabRefs.current.findIndex((tab) => tab === event.target)
    if (focusedIndex < 0) return

    let nextIndex: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = focusedIndex + 1
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = focusedIndex - 1
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = sections.length - 1

    if (nextIndex === null) return
    event.preventDefault()
    selectSection(nextIndex, true)
  }

  const activeLabel = sections.find((section) => section.id === activeSection)?.label ?? '封面'

  return (
    <section
      className="library-reader"
      aria-label="馆藏安全预览阅读器"
      onKeyDown={handleReaderKeyDown}
    >
      <header className="library-reader-header">
        <div>
          <p className="library-eyebrow">安全预览 · {book.cover[2]}</p>
          <h2 ref={headingRef} tabIndex={-1}>学科信息参考</h2>
          <p>只切换封面、目录和名词解释；按 Esc 返回馆藏。</p>
        </div>
        <button className="library-action library-reader-return" type="button" onClick={onClose}>
          返回馆藏
        </button>
      </header>

      <div
        className="library-reader-tabs"
        role="tablist"
        aria-label="安全预览内容"
        onKeyDown={handleTabKeyDown}
      >
        {sections.map((section, index) => (
          <button
            key={section.id}
            ref={(element) => { tabRefs.current[index] = element }}
            id={`library-tab-${section.id}`}
            className="library-reader-tab"
            type="button"
            role="tab"
            aria-controls={`library-panel-${section.id}`}
            aria-selected={activeSection === section.id}
            tabIndex={activeSection === section.id ? 0 : -1}
            onClick={() => selectSection(index, false)}
          >
            {section.label}
          </button>
        ))}
      </div>

      <div className="library-reader-content">
        <section
          id="library-panel-cover"
          className="library-reader-panel"
          role="tabpanel"
          aria-labelledby="library-tab-cover"
          tabIndex={0}
          hidden={activeSection !== 'cover'}
        >
          <div className="library-reader-cover-layout">
            <div className="library-reader-cover" aria-label="学科信息参考封面">
              <div className="library-reader-cover-top">
                <span>数字馆藏</span>
                <span className="library-reader-seal" aria-hidden="true">阅</span>
              </div>
              <div className="library-reader-cover-middle">
                <span className="library-reader-ornament" aria-hidden="true" />
                <p>{book.cover[1]}</p>
                <span>{book.cover[2]}</span>
              </div>
              <div className="library-reader-cover-bottom">
                <span>{book.cover[3]}</span>
                <span>文衡</span>
              </div>
            </div>
            <div className="library-reader-cover-details">
              <p className="library-eyebrow">封面</p>
              <h3>{book.cover[1]}</h3>
              <p>{book.cover[2]}</p>
              <p>{book.cover[3]}</p>
            </div>
          </div>
        </section>

        <section
          id="library-panel-toc"
          className="library-reader-panel"
          role="tabpanel"
          aria-labelledby="library-tab-toc"
          tabIndex={0}
          hidden={activeSection !== 'toc'}
        >
          <p className="library-eyebrow">目录</p>
          <h3>报告章节</h3>
          <ul className="library-reader-toc">
            {book.toc.map((entry, index) => (
              <li key={`${index}-${entry.title}`}>
                <span className="library-reader-bullet" aria-hidden="true">•</span>
                <span>{entry.title}</span>
              </li>
            ))}
          </ul>
        </section>

        <section
          id="library-panel-glossary"
          className="library-reader-panel"
          role="tabpanel"
          aria-labelledby="library-tab-glossary"
          tabIndex={0}
          hidden={activeSection !== 'glossary'}
        >
          <p className="library-eyebrow">名词解释</p>
          <h3>报告中的用语</h3>
          <dl className="library-reader-glossary">
            {book.glossary.map((entry, index) => (
              <div className="library-reader-term" key={`${index}-${entry.term}`}>
                <dt>{entry.term}</dt>
                <dd>{entry.definition}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      <footer className="library-reader-footer">
        <p aria-live="polite">当前内容：{activeLabel}</p>
        <button className="library-reader-back" type="button" onClick={onClose}>
          归架并返回馆藏
        </button>
      </footer>
    </section>
  )
}
