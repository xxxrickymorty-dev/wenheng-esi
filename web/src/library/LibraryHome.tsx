import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import type { GlossaryEntry, ShelfBookPreview } from './types'
import type { ReaderSection } from './Reader'
import './home.css'
import './home-overrides.css'

type LibraryHomeProps = {
  books: ShelfBookPreview[]
  onEnterExterior: () => void
  onOpenBook: (bookIndex: number, section: ReaderSection, trigger: HTMLButtonElement) => void
}

function ArrowUpRight({ size = 16 }: { size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M8 7h9v9" /></svg>
}

function ArrowDown({ size = 18 }: { size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v15m-6-6 6 6 6-6" /></svg>
}

function ArrowRight({ size = 20 }: { size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h15m-6-6 6 6-6 6" /></svg>
}

function SearchIcon() {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.5 4.5" /></svg>
}

function FeatureIcon({ kind }: { kind: number }) {
  const paths = [
    <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21z" /><path d="M4 5.5v15.2M8 7h8M8 10h8" /></>,
    <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>,
    <><path d="M5 3h10l4 4v14H5z" /><path d="M15 3v5h4M8 12h8M8 16h8" /></>,
    <><path d="M4 5h16M4 12h16M4 19h16" /><circle cx="7" cy="5" r="1" /><circle cx="7" cy="12" r="1" /><circle cx="7" cy="19" r="1" /></>,
  ]
  return <svg aria-hidden="true" width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">{paths[kind]}</svg>
}

function monthLabel(book: ShelfBookPreview): string {
  const month = book.cover[3].match(/(\d{4})年(\d{1,2})月/)
  return month ? `${month[1]}.${month[2].padStart(2, '0')}` : book.cover[2]
}

function issueLabel(book: ShelfBookPreview): string {
  const no = book.cover[2].match(/总第\s*(\d+)\s*期/)?.[1]
  return no ? `总第 ${no} 期` : book.cover[2]
}

function Header({ onEnterExterior, backToWorkspace }: { onEnterExterior: () => void; backToWorkspace?: boolean }) {
  const links = [['首页', '#home'], ['收藏', '#bookshelf'], ['学科索引', '#disciplines'], ['数据档案', '#archive'], ['关于本馆', '#about']]
  return <header className="home-header">
    <a href="#home" className="home-brand" aria-label="云南大学图书馆首页">
      <span className="home-wordmark">雲南大學</span>
      <span className="home-brand-divider" />
      <span className="home-brand-library">图书馆<small>YUNNAN UNIVERSITY LIBRARY</small></span>
    </a>
    <nav className="home-nav" aria-label="主导航">
      {backToWorkspace && <a className="home-nav-back" href="/app/" title="回到馆员工作区">← 回工作区</a>}
      {links.map(([label, href]) => <a key={href} href={href}>{label}</a>)}
    </nav>
    <button type="button" className="home-button header-entrance" onClick={onEnterExterior}>
      进入3D图书馆 <ArrowUpRight />
    </button>
  </header>
}

function HeroSection({ onEnterExterior }: { onEnterExterior: () => void }) {
  const hero = useRef<HTMLElement>(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => hero.current?.style.setProperty('--hero-shift', `${Math.min(48, window.scrollY * 0.08)}px`))
    }
    window.addEventListener('scroll', update, { passive: true })
    return () => { window.removeEventListener('scroll', update); cancelAnimationFrame(frame) }
  }, [])

  return <section className="home-hero" ref={hero} aria-labelledby="hero-title">
    <img className="home-hero-image" src={`${import.meta.env.BASE_URL}assets/ynu-library-real.png`} alt="云南大学呈贡校区图书馆，中央玻璃穹顶、红砖翼楼、双塔及入口广场" width={1280} height={720} fetchPriority="high" />
    <div className="home-hero-shade" />
    <div className="home-hero-content">
      <p className="home-kicker light"><span /> YUNNAN UNIVERSITY LIBRARY</p>
      <h1 id="hero-title">云南大学<br /><em>图书馆</em></h1>
      <p className="home-hero-subtitle">学科信息参考 <b>·</b> 数字馆藏 <b>·</b> 数据阅览</p>
      <div className="home-hero-actions">
        <button type="button" className="home-button ivory" onClick={onEnterExterior}>进入3D图书馆 <ArrowUpRight size={18} /></button>
        <a className="home-button translucent" href="#disciplines"><SearchIcon /> 学科检索</a>
      </div>
    </div>
    <div className="home-hero-caption"><span>呈贡校区 · 图书馆</span><small>会泽百家　至公天下</small></div>
    <a className="home-scroll" href="#collection" aria-label="向下浏览馆藏介绍"><ArrowDown /><span>向下阅览</span></a>
  </section>
}

function CollectionSection() {
  const entries = [
    { title: '学科信息参考', en: 'DISCIPLINARY REFERENCE', text: '以双月刊物记录学科发展，将每一期整理为可持续翻阅的馆藏。' },
    { title: '历期馆藏', en: 'PERIODICAL COLLECTION', text: '按期取阅，查看每册开放的封面、目录与名词解释。' },
    { title: '目录导览', en: 'TABLE OF CONTENTS', text: '从章节标题进入对应期次，先了解刊物的内容结构。' },
    { title: '名词解释', en: 'GLOSSARY', text: '阅读常见专业术语说明，了解刊物中的基础概念。' },
  ]
  return <section id="collection" className="home-intro home-container home-reveal">
    <div className="home-section-heading"><div><p className="home-kicker">THE READING ROOM</p><h2>一册一档，循数而读。</h2></div><p>从一本刊物出发，<br />看见云南大学学科信息的连续记录。</p></div>
    <div className="home-features">{entries.map((entry, index) => <article key={entry.title} className="home-feature"><div className="home-feature-top"><span>{String(index + 1).padStart(2, '0')}</span><FeatureIcon kind={index} /></div><h3>{entry.title}</h3><small>{entry.en}</small><p>{entry.text}</p></article>)}</div>
  </section>
}

function BookshelfSection({ books, onOpenBook, onEnterExterior }: LibraryHomeProps) {
  const visibleBooks = books.map((book, bookIndex) => ({ book, bookIndex })).reverse()
  return <section id="bookshelf" className="home-bookshelf">
    <div className="home-container home-reveal">
      <div className="home-section-heading"><div><p className="home-kicker">COLLECTION / A—01</p><h2>学科情报特藏</h2></div><div className="home-heading-aside"><span>历期馆藏 · 可阅预览</span><button type="button" className="home-heading-link" onClick={onEnterExterior}>走进阅览室 <ArrowUpRight /></button></div></div>
      {visibleBooks.length ? <div className="home-book-row">{visibleBooks.map(({ book, bookIndex }, index) => <button type="button" className={`home-book-item volume-${index}`} key={`${book.cover[2]}-${bookIndex}`} onClick={(event) => onOpenBook(bookIndex, 'cover', event.currentTarget)} aria-label={`打开${book.cover[2]}封面预览`}>
        <div className="home-book-cover">
          <div className="home-cover-head"><span>云南大学</span><small>YUNNAN UNIVERSITY</small></div>
          <div className="home-cover-title"><span>{book.cover[1]}</span><small>DISCIPLINARY<br />INFORMATION REFERENCE</small></div>
          <div className="home-cover-issue"><strong>{monthLabel(book)}</strong><span>{issueLabel(book)}</span></div>
          <div className="home-cover-bottom"><span>学科情报特藏</span><span>YNU · DIR</span></div>
        </div>
        <div className="home-book-info"><div><span>{monthLabel(book)}</span>{index === 0 && <small className="home-new-label">最新馆藏</small>}</div><span>{issueLabel(book)} <ArrowUpRight size={17} /></span></div>
      </button>)}</div> : <p className="home-empty-collection" role="status">目前没有可预览的馆藏。</p>}
      <div className="home-shelf-foot"><span><span className="home-catalog-square" /> 馆藏位置：学科情报特藏 A—01</span><span>封面 · 目录 · 名词解释</span></div>
    </div>
  </section>
}

function ArchiveSection() {
  return <section id="archive" className="home-archive"><div className="home-container home-archive-grid home-reveal">
    <div className="home-archive-copy"><p className="home-kicker light">SAFE PREVIEW</p><h2>每一本馆藏，<br />都有清晰的阅览边界。</h2><p>登录后可查看已开放期次的封面、目录与名词解释。点击馆藏即可在阅览室中打开安全预览。</p><a className="home-text-link" href="#bookshelf">浏览历期馆藏 <ArrowRight /></a></div>
    <div className="home-archive-card"><div className="home-archive-card-head"><span>馆藏阅读范围</span><small>COLLECTION ACCESS</small></div><dl><div><dt>封面</dt><dd>期次与编者信息</dd></div><div><dt>目录</dt><dd>章节标题与顺序</dd></div><div><dt>名词解释</dt><dd>专业术语与说明</dd></div><div><dt>其他报告内容</dt><dd>在册页中逐页阅览</dd></div></dl><p className="home-archive-note">登录后可阅览报告全内容</p></div>
  </div></section>
}

function PreviewIndexSection({ books, onOpenBook }: Pick<LibraryHomeProps, 'books' | 'onOpenBook'>) {
  const [query, setQuery] = useState('')
  const selectedBookIndex = books.length - 1
  const selectedBook = books[selectedBookIndex]
  const entries = useMemo(() => selectedBook ? [
    ...selectedBook.toc.map((entry) => ({ kind: 'toc' as const, title: entry.title, detail: '' })),
    ...selectedBook.glossary.map((entry: GlossaryEntry) => ({ kind: 'glossary' as const, title: entry.term, detail: entry.definition })),
  ] : [], [selectedBook])
  const filtered = useMemo(() => entries.filter((entry) => `${entry.title} ${entry.detail}`.toLowerCase().includes(query.trim().toLowerCase())), [entries, query])
  const [selectedTitle, setSelectedTitle] = useState('')
  const active = filtered.find((entry) => entry.title === selectedTitle) ?? filtered[0]

  function updateQuery(event: ChangeEvent<HTMLInputElement>) {
    setQuery(event.target.value)
    setSelectedTitle('')
  }

  return <section id="disciplines" className="home-disciplines home-container home-reveal">
    <div className="home-section-heading"><div><p className="home-kicker">SAFE CONTENT INDEX</p><h2>从目录，进入馆藏。</h2></div><p>检索目录标题与名词解释，<br />更多内容在册页中翻阅。</p></div>
    {selectedBook ? <div className="home-discipline-layout"><div className="home-index-panel">
      <label className="home-search" htmlFor="preview-search"><SearchIcon /><input id="preview-search" aria-label="检索目录与名词解释" type="search" placeholder="检索目录标题或名词解释" value={query} onChange={updateQuery} /><span>公开预览</span></label>
      <div className="home-index-head"><span>目录与名词解释</span><span>安全预览</span></div>
      <div className="home-index-results" aria-live="polite">{filtered.length ? filtered.slice(0, 8).map((entry) => <button key={`${entry.kind}-${entry.title}`} onClick={(event) => onOpenBook(selectedBookIndex, entry.kind, event.currentTarget)} className={`home-index-row ${active?.title === entry.title ? 'is-selected' : ''}`} aria-pressed={active?.title === entry.title}><span>{entry.title}<small>{entry.kind === 'toc' ? '目录' : '名词解释'}</small></span><span><ArrowUpRight size={17} /></span></button>) : <p className="home-search-empty">没有找到可阅内容，请换个关键词试试。</p>}</div>
      <p className="home-show-all" aria-live="polite">{filtered.length ? '选择一项，在阅览器中查看' : '当前没有匹配内容'}</p>
    </div>
    <article className="home-data-detail" aria-label="安全预览内容"><div className="home-data-heading"><p className="home-kicker">{monthLabel(selectedBook)} / {issueLabel(selectedBook)}</p><span>馆藏全内容</span></div><h3>{active?.title ?? '安全预览'}</h3><p className="home-data-en">{active?.kind === 'toc' ? 'TABLE OF CONTENTS' : active?.kind === 'glossary' ? 'GLOSSARY' : 'COVER · CONTENTS · GLOSSARY'}</p><p className="home-preview-summary">{active?.detail || '封面、目录与名词解释可在阅览器中查阅；登录后还可翻到指标、学科大表与双路线预测。'}</p><button type="button" className="home-detail-link" onClick={(event) => onOpenBook(selectedBookIndex, active?.kind ?? 'cover', event.currentTarget)}>在阅览器中查看 <ArrowUpRight size={17} /></button></article>
    </div> : <p className="home-empty-collection" role="status">目前没有可预览的目录或名词解释。</p>}
  </section>
}

function Footer({ onEnterExterior }: { onEnterExterior: () => void }) {
  return <><section id="about" className="home-about"><div className="home-container home-about-inner home-reveal"><span className="home-about-mark">阅</span><div><p className="home-kicker">ABOUT THE COLLECTION</p><h2>云南大学图书馆中的<br className="home-mobile-break" />数字学科阅览空间</h2><p>汇集《学科信息参考》馆藏，以安全预览连接封面、目录与名词解释。</p></div><button type="button" className="home-button dark" onClick={onEnterExterior}>进入3D图书馆 <ArrowUpRight size={17} /></button></div></section><footer className="home-footer"><div className="home-container"><div className="home-footer-main"><a href="#home" className="home-footer-brand">云南大学图书馆<small>YUNNAN UNIVERSITY LIBRARY</small></a><div><strong>学科情报服务</strong><p>馆藏预览：封面、目录与名词解释</p></div><nav aria-label="页脚导航"><a href="#bookshelf">数字馆藏</a><a href="#disciplines">学科索引</a><a href="#archive">数据档案</a></nav></div><div className="home-footer-bottom"><span>云南大学图书馆　<i>·</i>　学科信息参考</span><span>会泽百家　至公天下</span></div></div></footer></>
}

export default function LibraryHome({ books, onEnterExterior, onOpenBook, backToWorkspace }: LibraryHomeProps & { backToWorkspace?: boolean }) {
  useEffect(() => {
    const sections = document.querySelectorAll<HTMLElement>('.home-reveal')
    if (!window.IntersectionObserver || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
      if (!entry.isIntersecting) return
      entry.target.classList.add('is-visible')
      observer.unobserve(entry.target)
    }), { threshold: 0.08 })
    sections.forEach((section) => { section.classList.add('reveal-enabled'); observer.observe(section) })
    return () => observer.disconnect()
  }, [])

  return <div className="library-home" id="home">
    <a className="home-skip" href="#bookshelf">跳转到数字馆藏</a>
    <Header onEnterExterior={onEnterExterior} backToWorkspace={backToWorkspace} />
    <main>
      <HeroSection onEnterExterior={onEnterExterior} />
      <div className="home-record-strip"><div className="home-container"><span>学科情报阅览室<small>DISCIPLINE INTELLIGENCE READING ROOM</small></span><div><span>可阅览</span><strong>全内容册页</strong></div></div></div>
      <CollectionSection />
      <BookshelfSection books={books} onOpenBook={onOpenBook} onEnterExterior={onEnterExterior} />
      <ArchiveSection />
      <PreviewIndexSection books={books} onOpenBook={onOpenBook} />
    </main>
    <Footer onEnterExterior={onEnterExterior} />
  </div>
}
