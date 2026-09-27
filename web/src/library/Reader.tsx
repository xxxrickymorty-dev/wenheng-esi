import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { libraryAudio } from './library-audio'
import type { GlossaryEntry, ShelfBookPreview } from './types'
import './experience.css'
import './flip-reader.css'

export type ReaderSection = 'cover' | 'toc' | 'glossary'

type ReaderProps = {
  books: ShelfBookPreview[]
  bookIndex: number
  initialSection: ReaderSection
  motion: boolean
  soundEnabled: boolean
  onMotionChange: (motion: boolean) => void
  onSoundToggle: () => void
  onBackHome: () => void
  onSelectBook: (index: number) => void
  onClose: () => void
}

type FlipEvent<T = unknown> = {
  data: T
}

type PageFlipInstance = {
  loadFromHTML: (pages: HTMLElement[]) => void
  destroy: () => void
  on: (event: string, callback: (event: FlipEvent<number>) => void) => void
  flipNext: () => void
  flipPrev: () => void
  getCurrentPageIndex: () => number
}

type PageFlipNamespace = {
  PageFlip: new (host: HTMLElement, settings: Record<string, unknown>) => PageFlipInstance
}

declare global {
  interface Window {
    St?: PageFlipNamespace
  }
}

const PAGE_FLIP_SRC = `${import.meta.env.BASE_URL}vendor/page-flip.browser.js`

let pageFlipLoader: Promise<PageFlipNamespace> | null = null

/** 按需加载本地翻页组件；脚本随构建产物一起发布，不走外部网络。 */
function loadPageFlip() {
  if (window.St?.PageFlip) return Promise.resolve(window.St)
  if (pageFlipLoader) return pageFlipLoader

  pageFlipLoader = new Promise<PageFlipNamespace>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-ynu-pageflip="true"]')
    const finish = () => {
      if (window.St?.PageFlip) resolve(window.St)
      else reject(new Error('翻页组件加载后没有就绪'))
    }

    if (existing) {
      existing.addEventListener('load', finish, { once: true })
      existing.addEventListener('error', () => reject(new Error('翻页组件没有加载成功')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = PAGE_FLIP_SRC
    script.async = true
    script.dataset.ynuPageflip = 'true'
    script.addEventListener('load', finish, { once: true })
    script.addEventListener('error', () => reject(new Error('翻页组件没有加载成功')), { once: true })
    document.head.appendChild(script)
  })

  return pageFlipLoader
}

type FlipLeafModel =
  | { kind: 'cover' }
  | { kind: 'record' }
  | { kind: 'toc' }
  | { kind: 'glossary'; entries: GlossaryEntry[]; part: number; parts: number }
  | { kind: 'end' }

/** 访客安全预览的册页：封面 → 馆藏登记 → 目录 → 名词解释 → 阅毕归架。 */
function buildLeaves(book: ShelfBookPreview): FlipLeafModel[] {
  const groups: GlossaryEntry[][] = []
  for (let index = 0; index < book.glossary.length; index += 4) {
    groups.push(book.glossary.slice(index, index + 4))
  }

  return [
    { kind: 'cover' },
    { kind: 'record' },
    { kind: 'toc' },
    ...groups.map((entries, index) => ({ kind: 'glossary' as const, entries, part: index + 1, parts: groups.length })),
    { kind: 'end' },
  ]
}

function startLeafIndex(leaves: FlipLeafModel[], section: ReaderSection) {
  if (section === 'cover') return 0
  const index = leaves.findIndex((leaf) => leaf.kind === section)
  return index >= 0 ? index : 0
}

function issueParts(book: ShelfBookPreview) {
  const matched = book.cover[2].match(/^(\d{4}年第\d+期)（(总第\d+期)）$/)
  return {
    periodLabel: matched?.[1] ?? book.cover[2],
    totalIssueLabel: matched?.[2] ?? null,
    issueNumber: book.cover[2].match(/总第\s*(\d+)\s*期/)?.[1] ?? null,
    month: book.cover[3].match(/(\d{4})年(\d{1,2})月/),
  }
}

function Leaf({ book, n, children }: { book: ShelfBookPreview; n: number; children: ReactNode }) {
  const label = String(n + 1).padStart(2, '0')
  return <>
    <div className="page-head"><span>云南大学图书馆 / 学科信息参考</span><span>{label}</span></div>
    <div className="page-body">{children}</div>
    <div className="page-foot"><span>YNU · DIR · {book.cover[2]}</span><span>{label}</span></div>
  </>
}

function ReferenceCover({ book }: { book: ShelfBookPreview }) {
  const { periodLabel, totalIssueLabel } = issueParts(book)
  return <div className="cover-page reference-cover">
    <div className="reference-cover-top">
      <span className="reference-cover-brand">云南大学<small>YUNNAN UNIVERSITY</small></span>
      <span className="reference-cover-collection">学科服务馆藏</span>
    </div>
    <div className="reference-cover-title">
      <h2>{book.cover[1]}</h2>
      <p>DISCIPLINARY INFORMATION REFERENCE</p>
      <span className="reference-cover-divider"><i /></span>
      <strong>{periodLabel}</strong>
      {totalIssueLabel && <em>{totalIssueLabel}</em>}
    </div>
    <svg className="reference-campus-art" viewBox="0 0 520 210" aria-hidden="true">
      <path d="M52 154H468M78 154L112 106H184L204 73H316L336 106H408L442 154" />
      <path d="M182 154V101H338V154M217 154V92H303V154" />
      <path d="M230 92V72H290V92M244 72V58H276V72" />
      <path d="M135 154V120H171V154M349 154V120H385V154" />
      <path d="M214 169H306M201 178H319M188 187H332M174 196H346" />
      <path d="M230 110V146M248 110V146M266 110V146M284 110V146" />
    </svg>
    <div className="reference-cover-footer">
      <span className="reference-seal"><b>雲</b><small>1923</small></span>
      <span className="reference-motto">会泽百家&nbsp;&nbsp;至公天下<small>YUNNAN UNIVERSITY</small></span>
    </div>
  </div>
}

function leafContent(book: ShelfBookPreview, leaf: FlipLeafModel, n: number) {
  if (leaf.kind === 'cover') return <ReferenceCover book={book} />
  if (leaf.kind === 'record') return <Leaf book={book} n={n}>
    <p className="kicker">COLLECTION RECORD</p>
    <h2>馆藏登记</h2>
    <div className="catalog-fields">
      <span>刊名</span><strong>{book.cover[1]}</strong>
      <span>期次</span><strong>{book.cover[2]}</strong>
      <span>编印</span><strong>{book.cover[3]}</strong>
      <span>状态</span><strong>在架 · 可取阅</strong>
    </div>
    <p className="catalog-quote">一册一档，循数而读。</p>
  </Leaf>
  if (leaf.kind === 'toc') return <Leaf book={book} n={n}>
    <p className="kicker">TABLE OF CONTENTS</p>
    <h2>目录</h2>
    <ol className="reader-toc-list">
      {book.toc.map((entry, index) => <li key={`${index}-${entry.title}`}>
        <span className="reader-toc-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <span className="reader-toc-title">{entry.title}</span>
        {entry.page && <span className="reader-toc-page">第 {entry.page} 页</span>}
      </li>)}
    </ol>
  </Leaf>
  if (leaf.kind === 'glossary') return <Leaf book={book} n={n}>
    <p className="kicker">GLOSSARY</p>
    <h2>名词解释{leaf.parts > 1 ? `（${leaf.part}/${leaf.parts}）` : ''}</h2>
    <dl className="reader-glossary-list">
      {leaf.entries.map((entry, index) => <div className="reader-glossary-entry" key={`${index}-${entry.term}`}>
        <dt>{entry.term}</dt>
        <dd>{entry.definition}</dd>
      </div>)}
    </dl>
  </Leaf>
  return <Leaf book={book} n={n}>
    <div className="end-page">
      <span className="end-emblem" aria-hidden="true">雲</span>
      <h2>阅毕归架</h2>
      <p>本册为访客安全预览，开放封面、目录与名词解释；报告正文、数值页、图表与附件不在预览范围内。</p>
      <div className="end-rule" aria-hidden="true" />
      <strong>云南大学图书馆<br />学科情报特藏</strong>
      <small>YUNNAN UNIVERSITY LIBRARY</small>
    </div>
  </Leaf>
}

/** 文字版：屏幕阅读器与翻页组件加载失败时都能完整读到预览内容。 */
function ReadableSections({ book }: { book: ShelfBookPreview }) {
  return <>
    <section>
      <h3>封面</h3>
      <p>{book.cover[1]} · {book.cover[2]}</p>
      <p>{book.cover[3]}</p>
    </section>
    <section>
      <h3>目录</h3>
      <ol>{book.toc.map((entry, index) => <li key={`${index}-${entry.title}`}>{entry.title}{entry.page ? `（第 ${entry.page} 页）` : ''}</li>)}</ol>
    </section>
    <section>
      <h3>名词解释</h3>
      <dl>{book.glossary.map((entry, index) => <div key={`${index}-${entry.term}`}><dt>{entry.term}</dt><dd>{entry.definition}</dd></div>)}</dl>
    </section>
  </>
}

export default function Reader({
  books,
  bookIndex,
  initialSection,
  motion,
  soundEnabled,
  onMotionChange,
  onSoundToggle,
  onBackHome,
  onSelectBook,
  onClose,
}: ReaderProps) {
  const book = books[bookIndex]
  const leaves = useMemo(() => (book ? buildLeaves(book) : []), [book])
  const wrapRef = useRef<HTMLDivElement>(null)
  const templatesRef = useRef<HTMLDivElement>(null)
  const flipRef = useRef<PageFlipInstance | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const motionRef = useRef(motion)
  motionRef.current = motion
  const [pageIndex, setPageIndex] = useState(0)
  const [flipError, setFlipError] = useState(false)

  const previousPage = useCallback(() => flipRef.current?.flipPrev(), [])
  const nextPage = useCallback(() => flipRef.current?.flipNext(), [])

  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!book) return
    const wrap = wrapRef.current
    const templates = templatesRef.current
    let cancelled = false
    let instance: PageFlipInstance | null = null

    setPageIndex(0)
    setFlipError(false)

    const init = async () => {
      try {
        const St = await loadPageFlip()
        if (cancelled || !wrap || !templates) return

        wrap.innerHTML = ''
        const host = document.createElement('div')
        host.className = 'flipbook-host'
        host.id = 'flipbook'
        wrap.appendChild(host)

        const pages = Array.from(templates.children).map((node) => node.cloneNode(true) as HTMLElement)
        pages.forEach((page) => host.appendChild(page))

        instance = new St.PageFlip(host, {
          width: 420,
          height: 600,
          size: 'stretch',
          minWidth: 280,
          maxWidth: 700,
          minHeight: 400,
          maxHeight: 1000,
          maxShadowOpacity: 0.34,
          showCover: true,
          mobileScrollSupport: false,
          usePortrait: true,
          drawShadow: true,
          flippingTime: motionRef.current ? 680 : 140,
          startZIndex: 1,
          autoSize: true,
          useMouseEvents: true,
          showPageCorners: true,
          swipeDistance: 20,
          startPage: startLeafIndex(leaves, initialSection),
        })

        flipRef.current = instance
        instance.loadFromHTML(pages)
        // 起始页在装载时已定位（如从名词解释直接进入），同步页码后再监听翻页，
        // 避免装载本身触发一次翻页音效。
        setPageIndex(instance.getCurrentPageIndex())
        instance.on('flip', (event) => {
          setPageIndex(Number(event.data) || 0)
          libraryAudio.playPage()
        })
      } catch (error) {
        console.error('翻页阅读器初始化失败：', error)
        if (!cancelled) setFlipError(true)
      }
    }

    void init()

    return () => {
      cancelled = true
      if (instance) {
        try {
          instance.destroy()
        } catch {
          // 卸载时组件可能已自行清理宿主节点，重复销毁直接忽略。
        }
      }
      flipRef.current = null
      if (wrap) wrap.innerHTML = ''
    }
  }, [book, leaves, initialSection])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return
      const target = event.target as HTMLElement | null
      if (target && target.closest('select, input, textarea')) return

      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        nextPage()
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        previousPage()
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nextPage, previousPage, onClose])

  if (!book) return null

  const { totalIssueLabel } = issueParts(book)
  const pageCount = leaves.length
  const counter = String(Math.min(pageCount, pageIndex + 1)).padStart(2, '0')
  const issueOption = (item: ShelfBookPreview) => {
    const parts = issueParts(item)
    const date = parts.month ? `${parts.month[1]}年${Number(parts.month[2])}月` : item.cover[2]
    return parts.issueNumber ? `总第 ${parts.issueNumber} 期 · ${date}` : item.cover[2]
  }

  return <section className="site stage-reader">
    <div className="scene-wrap" aria-hidden="true">
      <div className="reading-backdrop" />
    </div>

    <div className="grain" aria-hidden="true" />

    <header className="topbar">
      <button className="brand" type="button" onClick={onBackHome} aria-label="返回数字图书馆首页">
        <span className="brand-mark">雲</span>
        <span><strong>云南大学图书馆</strong><small>YUNNAN UNIVERSITY LIBRARY</small></span>
      </button>
      <div className="topbar-right">
        <span>阅览中 · {totalIssueLabel ?? book.cover[2]}</span>
        <i aria-hidden="true" />
        <button
          className="sound-toggle"
          type="button"
          onClick={onSoundToggle}
          aria-label="背景音乐与书本音效"
          aria-pressed={soundEnabled}
          title={soundEnabled ? '关闭背景音乐与书本音效' : '开启背景音乐与书本音效'}
        >
          {soundEnabled ? '声音开启' : '声音关闭'}
        </button>
        <i aria-hidden="true" />
        <button type="button" onClick={() => onMotionChange(!motion)} aria-label="场景动效" aria-pressed={motion}>
          {motion ? '动效开启' : '动效关闭'}
        </button>
      </div>
    </header>

    <h2 className="reader-sr-only" tabIndex={-1} ref={headingRef}>
      学科信息参考 · {book.cover[2]} 访客安全预览
    </h2>

    <div className="reader flip-reader">
      <div className="reader-toolbar">
        <button type="button" onClick={onClose}>← 归架</button>
        <span>云南大学图书馆 <i>·</i> 学科情报阅览室</span>
        <button type="button" onClick={onClose}>关闭 ×</button>
      </div>

      <div className="reading-area flip-reading-area">
        <div className="flip-wrap" ref={wrapRef}>
          {flipError && <div className="flip-fallback">
            <strong>翻页组件没有加载成功，先以文字版显示本册内容。</strong>
            <ReadableSections book={book} />
          </div>}
        </div>
      </div>

      <div className="flip-page-templates" ref={templatesRef} aria-hidden="true">
        {leaves.map((leaf, index) => <article
          key={`${book.cover[2]}-${index}`}
          className="flip-page"
          data-density={index === 0 || index === pageCount - 1 ? 'hard' : 'soft'}
        >
          <div className="flip-page-shell">{leafContent(book, leaf, index)}</div>
        </article>)}
      </div>

      <div className="reader-controls flip-reader-controls">
        <div className="issue-switch">
          <label htmlFor="reader-issue">馆藏期次</label>
          <select
            id="reader-issue"
            value={bookIndex}
            onChange={(event) => {
              const nextIndex = Number(event.target.value)
              if (nextIndex === bookIndex) return
              libraryAudio.playPull()
              onSelectBook(nextIndex)
            }}
          >
            {books.map((item, index) => <option key={`${item.cover[2]}-${index}`} value={index}>
              {issueOption(item)}
            </option>)}
          </select>
        </div>

        <div className="page-controls">
          <button type="button" onClick={previousPage} disabled={pageIndex <= 0} aria-label="上一页">←</button>
          <span className="page-counter" aria-live="polite" aria-atomic="true">
            {counter}<small> / {pageCount}</small>
          </span>
          <button type="button" onClick={nextPage} disabled={pageIndex >= pageCount - 1} aria-label="下一页">→</button>
        </div>

        <span className="reader-hint">拖动页角翻页 · ← → 键翻页 · ESC 归架</span>
      </div>
    </div>

    <div className="reader-sr-only" role="region" aria-label="安全预览文字版">
      <ReadableSections book={book} />
    </div>
  </section>
}
