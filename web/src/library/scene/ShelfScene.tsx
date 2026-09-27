import type { MouseEvent } from 'react'
import type { ShelfBookPreview } from '../types'
import type { ReaderSection } from '../Reader'

type ShelfSceneProps = {
  books: ShelfBookPreview[]
  onOpen: (bookIndex: number, section: ReaderSection, trigger: HTMLButtonElement) => void
}

export default function ShelfScene({ books, onOpen }: ShelfSceneProps) {
  function open(section: ReaderSection, bookIndex: number, event: MouseEvent<HTMLButtonElement>) {
    onOpen(bookIndex, section, event.currentTarget)
  }

  return (
    <section className="library-shelf-scene" aria-labelledby="library-shelf-title">
      <header className="library-shelf-heading">
        <div>
          <p className="library-eyebrow">访客阅览 · 历期馆藏</p>
          <h2 id="library-shelf-title">在馆藏中取阅一份报告</h2>
          <p>每个可预览期次各陈列一册，可直接打开封面、目录或名词解释。</p>
        </div>
        <span className="library-shelf-badge">仅限安全预览</span>
      </header>

      <div className="library-shelf-banner" role="note">
        <span className="library-shelf-banner-mark" aria-hidden="true">阅</span>
        <p><strong>访客可阅内容</strong>封面、目录和名词解释。阅览室不提供报告正文、数值页、图表、下载或运行状态。</p>
      </div>

      <div className="library-book-grid">
        {books.map((book, bookIndex) => (
          <article className="library-book-card" key={`${book.cover[2]}-${bookIndex}`}>
            <div className="library-book-card-cover" aria-hidden="true">
              <div className="library-book-card-top">
                <span>数字馆藏</span>
                <span className="library-reader-seal">阅</span>
              </div>
              <div className="library-book-card-middle">
                <span className="library-reader-ornament" />
                <strong>{book.cover[1]}</strong>
                <span>{book.cover[2]}</span>
              </div>
              <div className="library-book-card-bottom">
                <span>{book.cover[3]}</span>
                <span>文衡</span>
              </div>
            </div>

            <div className="library-book-card-body">
              <p className="library-eyebrow">安全预览</p>
              <h3>{book.cover[1]}</h3>
              <p className="library-book-period">{book.cover[2]}</p>
              <div className="library-book-actions" aria-label={`${book.cover[2]}可阅内容`}>
                <button type="button" onClick={(event) => open('cover', bookIndex, event)}>打开封面</button>
                <button type="button" onClick={(event) => open('toc', bookIndex, event)}>查看目录</button>
                <button type="button" onClick={(event) => open('glossary', bookIndex, event)}>查阅名词解释</button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
