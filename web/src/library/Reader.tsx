import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { libraryAudio } from './library-audio'
import type { ForecastRow, GlossaryEntry, ReportBlock, ReportCell,
              ShelfBook, ShelfTableRow } from './types'
import './experience.css'
import './flip-reader.css'

export type ReaderSection = 'cover' | 'toc' | 'glossary'

type ReaderProps = {
  books: ShelfBook[]
  bookIndex: number
  initialSection: ReaderSection
  motion: boolean
  soundEnabled: boolean
  onMotionChange: (motion: boolean) => void
  onSoundToggle: () => void
  onBackHome: () => void
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
  | { kind: 'report'; blocks: ReportBlock[] }
  | { kind: 'checkup' }
  | { kind: 'kpi' }
  | { kind: 'table'; rows: ShelfTableRow[]; offset: number; total: number; part: number; parts: number }
  | { kind: 'top' }
  | { kind: 'forecast'; route: 1 | 2; rows: ForecastRow[] }
  | { kind: 'end' }

/** 报告正文分页（票 05，2026-10-11）：章标题起新页；图按高度占位（小图可同页）；
    表按行分页（表头每页重排）。估行单位≈1 行正文；每页容量 ≈ 27 行（rick：全书画到约 30 页）。 */
function paginateReport(blocks: ReportBlock[]): ReportBlock[][] {
  const CAP = 29
  const pages: ReportBlock[][] = []
  let cur: ReportBlock[] = []
  let used = 0
  const flush = () => { if (cur.length) { pages.push(cur); cur = []; used = 0 } }
  const weight = (b: ReportBlock): number => {
    if (b.t === 'h1') return 3
    if (b.t === 'h2') return 2
    if (b.t === 'img') return 9           /* 显示高 ≈ 230px（CSS 夹住），两图可同页 */
    if (b.t === 'p') return Math.ceil(b.text.length / 24) + 0.6
    return 1
  }
  for (const b of blocks) {
    if (b.t === 'tbl') {
      flush()
      const rows = b.rows
      if (!rows.length) continue
      const header = rows[0]
      let chunk: ReportCell[][] = []
      let cu = 0
      const emit = () => {
        if (!chunk.length) return
        pages.push([{ t: 'tbl', rows: [header, ...chunk] }])
        chunk = []
        cu = 0
      }
      for (const row of rows.slice(1)) {
        const w = row.some((c) => (c.imgs?.length ?? 0) > 0) ? 3 : 1
        if (cu + w > 14) emit()
        chunk.push(row)
        cu += w
      }
      emit()
      if (rows.length === 1) pages.push([{ t: 'tbl', rows }])
      continue
    }
    const w = weight(b)
    /* 带图的页留白更大：图占的视觉高度比估行更实，装不下就翻页（防页底被裁） */
    const cap = cur.some((x) => x.t === 'img') ? 21 : CAP
    if (b.t === 'h1' && cur.length) flush()
    if (used + w > cap) flush()
    cur.push(b)
    used += w
  }
  flush()
  return pages
}

/** 册页：封面 → 馆藏登记 → 目录 → 名词解释 →（有完整数据时）报告正文（多页）/
    数字体检 / 本期指标 / 学科大表 / 顶尖论文·近线 / 双路线预测 → 阅毕归架。 */
function buildLeaves(book: ShelfBook): FlipLeafModel[] {
  const groups: GlossaryEntry[][] = []
  for (let index = 0; index < book.glossary.length; index += 4) {
    groups.push(book.glossary.slice(index, index + 4))
  }

  const leaves: FlipLeafModel[] = [
    { kind: 'cover' },
    { kind: 'record' },
    { kind: 'toc' },
    ...groups.map((entries, index) => ({ kind: 'glossary' as const, entries, part: index + 1, parts: groups.length })),
  ]

  const full = book.full
  if (full) {
    for (const blocks of paginateReport(full.report_text ?? [])) {
      leaves.push({ kind: 'report', blocks })
    }
    leaves.push({ kind: 'checkup' })
    leaves.push({ kind: 'kpi' })
    const rows = full.table ?? []
    const chunk = 12
    const parts = Math.max(1, Math.ceil(rows.length / chunk))
    for (let index = 0; index < parts; index += 1) {
      leaves.push({ kind: 'table', rows: rows.slice(index * chunk, (index + 1) * chunk),
                    offset: index * chunk, total: rows.length, part: index + 1, parts })
    }
    leaves.push({ kind: 'top' })
    leaves.push({ kind: 'forecast', route: 1, rows: full.forecast?.rows ?? [] })
    leaves.push({ kind: 'forecast', route: 2, rows: full.forecast?.rows2 ?? [] })
  }

  leaves.push({ kind: 'end' })
  return leaves
}

function startLeafIndex(leaves: FlipLeafModel[], section: ReaderSection) {
  if (section === 'cover') return 0
  const index = leaves.findIndex((leaf) => leaf.kind === section)
  return index >= 0 ? index : 0
}

function issueParts(book: ShelfBook) {
  const matched = book.cover[2].match(/^(\d{4}年第\d+期)（(总第\d+期)）$/)
  return {
    periodLabel: matched?.[1] ?? book.cover[2],
    totalIssueLabel: matched?.[2] ?? null,
    issueNumber: book.cover[2].match(/总第\s*(\d+)\s*期/)?.[1] ?? null,
    month: book.cover[3].match(/(\d{4})年(\d{1,2})月/),
  }
}

function Leaf({ book, n, children }: { book: ShelfBook; n: number; children: ReactNode }) {
  const label = String(n + 1).padStart(2, '0')
  return <>
    <div className="page-head"><span>云南大学图书馆 / 学科信息参考</span><span>{label}</span></div>
    <div className="page-body">{children}</div>
    <div className="page-foot"><span>YNU · DIR · {book.cover[2]}</span><span>{label}</span></div>
  </>
}

function ReferenceCover({ book }: { book: ShelfBook }) {
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

/** 报告正文块渲染（票 05）：标题/段落按纸面版式；插图与表格走只读图片口
    `/api/periods/{期次}/report-image/{rid}`（服务端从 docx 现取，不落盘）。 */
function renderReportBlock(book: ShelfBook, b: ReportBlock, key: number) {
  const imgSrc = (rid: string) =>
    `/api/periods/${encodeURIComponent(book.period ?? '')}/report-image/${encodeURIComponent(rid)}`
  if (b.t === 'h1') return <h3 className="rp-h1" key={key}>{b.text}</h3>
  if (b.t === 'h2') return <h4 className="rp-h2" key={key}>{b.text}</h4>
  if (b.t === 'p') return <p className="rp-p" key={key}>{b.text}</p>
  if (b.t === 'img') return <figure className="rp-fig" key={key}>
    <img src={imgSrc(b.rid)} alt="报告插图" loading="lazy" decoding="async" />
  </figure>
  if (b.t === 'tbl') return <table className="rp-tbl" key={key}><tbody>
    {b.rows.map((row, ri) => <tr key={ri}>
      {row.map((cell, ci) => (
        <td key={ci} colSpan={cell.span && cell.span > 1 ? cell.span : undefined}>
          {cell.text && <span className="rp-td">{cell.text}</span>}
          {(cell.imgs ?? []).map((rid) => (
            <img key={rid} src={imgSrc(rid)} alt="" loading="lazy" decoding="async" />
          ))}
        </td>
      ))}
    </tr>)}
  </tbody></table>
  return null
}

function subjectCn(book: ShelfBook): Map<string, string> {
  const map = new Map<string, string>()
  for (const row of book.full?.table ?? []) {
    if (row.en && row.cn) map.set(row.en, row.cn)
  }
  return map
}

function pctText(value?: number | null): string {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '—'
}

function forecastStatus(row: ForecastRow): { text: string; cls: string } {
  const mape = Number.parseFloat(row.mape)
  if (Number.isFinite(mape) && mape >= 5) return { text: '临时基线', cls: 'base' }
  if (row.t1 && row.t1 !== '—') return { text: '过线信号', cls: 'sig' }
  return { text: '持续观察', cls: 'watch' }
}

function leafContent(book: ShelfBook, leaf: FlipLeafModel, n: number) {
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
  if (leaf.kind === 'report') return <Leaf book={book} n={n}>
    <p className="kicker">REPORT · 正文</p>
    {leaf.blocks.map((b, i) => renderReportBlock(book, b, i))}
  </Leaf>
  if (leaf.kind === 'checkup') {
    const full = book.full
    return <Leaf book={book} n={n}>
      <p className="kicker">DIGITAL CHECKUP</p>
      <h2>数字体检</h2>
      <div className="kpi-grid">
        <div className="kpi"><span>断言通过</span>
          <strong>{full?.n_assert_pass ?? '—'}<i>/{full?.n_assert_total ?? '—'}</i></strong></div>
        <div className="kpi"><span>覆盖窗口</span>
          <strong className="small">{full?.coverage || '—'}</strong></div>
        <div className="kpi"><span>上期对照</span>
          <strong className="small">{full?.prev_label || '—'}</strong></div>
      </div>
      <div className="note-box">出稿前机器逐项自检；有一条未过，报告会带《诊断报告》并可回查。</div>
    </Leaf>
  }
  if (leaf.kind === 'kpi') {
    const full = book.full
    const delta = (value?: number | null) =>
      typeof value === 'number' && value > 0 ? <i>↑{value}</i> : null
    return <Leaf book={book} n={n}>
      <p className="kicker">THIS ISSUE</p>
      <h2>本期指标</h2>
      <div className="kpi-grid">
        <div className="kpi"><span>国际排名</span>
          <strong>{full?.rank_intl_now ?? '—'}{delta(full?.rank_intl_delta)}</strong></div>
        <div className="kpi"><span>国内高校排名</span>
          <strong>{full?.rank_cn_uni_now ?? '—'}</strong></div>
        <div className="kpi"><span>前 1% 学科</span>
          <strong>{full?.n_disc_1pct ?? '—'}</strong></div>
        <div className="kpi"><span>顶尖论文</span>
          <strong>{full?.top_papers_now ?? '—'}{delta(full?.top_papers_delta)}</strong></div>
      </div>
      <div className="note-box">与上期（{full?.prev_label || '上期'}）相比；数字取自本机部署产物，与工作台同一份事实。</div>
    </Leaf>
  }
  if (leaf.kind === 'table') {
    return <Leaf book={book} n={n}>
      <p className="kicker">DISCIPLINE TABLE</p>
      <h2>学科大表{leaf.parts > 1 ? `（${leaf.part}/${leaf.parts}）` : ''}</h2>
      <table className="data-table">
        <thead><tr>
          <th>学科</th><th className="num">论文</th><th className="num">被引</th>
          <th className="num">CNCI</th><th className="num">顶尖</th><th className="num">阈值</th>
          <th className="num">差距</th><th className="num">接近度</th><th className="num">位次</th>
        </tr></thead>
        <tbody>
          {leaf.rows.map((row) => <tr key={`${row.en}-${row.cn}`}>
            <td>{row.cn || row.en}</td>
            <td className="num">{row.papers ?? '—'}</td>
            <td className="num">{row.cites ?? '—'}</td>
            <td className="num">{typeof row.cnci === 'number' ? row.cnci.toFixed(2) : '—'}</td>
            <td className="num">{row.top ?? '—'}</td>
            <td className="num">{row.thr ?? '—'}</td>
            <td className="num">{row.gap ?? '—'}</td>
            <td className="num">{row.prox || '—'}</td>
            <td className="num">{row.rank || '—'}</td>
          </tr>)}
        </tbody>
      </table>
      <p className="table-note">共 {leaf.total} 个学科 · 数据源 table2.csv（第 {leaf.offset + 1}–{leaf.offset + leaf.rows.length} 行）</p>
    </Leaf>
  }
  if (leaf.kind === 'top') {
    const cn = subjectCn(book)
    const full = book.full
    const top3 = full?.top3 ?? []
    const best = full?.best_permille
    const near = full?.not_entered ?? []
    return <Leaf book={book} n={n}>
      <p className="kicker">TOP PAPERS &amp; NEAR-LINE</p>
      <h2>顶尖论文与近线学科</h2>
      <div className="note-box">
        <strong>顶尖论文学科前 3</strong>
        <p>{top3.length
          ? top3.map(([en, count]) => `${cn.get(en) ?? en} ${count} 篇`).join(' · ')
          : '—'}</p>
      </div>
      <div className="note-box">
        <strong>最接近 ESI 前 1‰</strong>
        <p>{best
          ? `${cn.get(best.discipline) ?? best.discipline} —— 接近度 ${pctText(best.prox_pct)}`
          : '—'}</p>
      </div>
      <div className="note-box">
        <strong>未进榜但已接近 1% 阈值</strong>
        {near.length
          ? near.map((item) => <p key={item.discipline}>
              {cn.get(item.discipline) ?? item.discipline} —— 接近度 {pctText(item.prox_pct)}
              {typeof item.chg === 'number'
                ? `（较上期 ${item.chg >= 0 ? '+' : ''}${item.chg.toFixed(2)}pp）` : ''}
            </p>)
          : <p>—</p>}
      </div>
    </Leaf>
  }
  if (leaf.kind === 'forecast') {
    const cn = subjectCn(book)
    const full = book.full
    return <Leaf book={book} n={n}>
      <p className="kicker">FORECAST · ROUTE {leaf.route}</p>
      <h2>{leaf.route === 1 ? '双路线预测 · 总被引 / 前 1% 阈值'
                            : '双路线预测 · 国内排名 / 前 1% 机构数'}</h2>
      {leaf.rows.length === 0
        ? <div className="note-box"><strong>本期暂无预测产物</strong>
            <p>该期未生成「预测选模与过线」，因此本页留空；有产物的期次会完整列出。</p></div>
        : <table className="data-table">
        <thead><tr>
          <th>学科</th><th>当前模型</th><th className="num">滚动 MAPE</th><th className="num">接近度</th>
          <th className="num">最早</th><th className="num">较可能</th><th className="num">最晚</th><th>状态</th>
        </tr></thead>
        <tbody>
          {leaf.rows.map((row) => {
            const status = forecastStatus(row)
            return <tr key={`${leaf.route}-${row.en}`}>
              <td>{cn.get(row.en) ?? row.en}</td>
              <td>{row.model}</td>
              <td className="num">{row.mape}</td>
              <td className="num">{row.prox}</td>
              <td className="num">{row.t1}</td>
              <td className="num">{row.t2}</td>
              <td className="num">{row.t3}</td>
              <td><span className={`badge ${status.cls}`}>{status.text}</span></td>
            </tr>
          })}
        </tbody>
      </table>}
      {leaf.route === 2 && <div className="note-box">
        <strong>判定口径</strong>
        <p>路线 1：预测总被引 ÷ 预测 ESI 前 1% 阈值；路线 2：预测前 1% 机构数 ÷ 预测云大国内排名（辅助条件）。
          过线是滚动监测信号，不等同于正式入榜时间或入榜概率。</p>
        {full?.forecast?.window && <p className="muted-small">
          序列窗口 {full.forecast.window}{full.forecast.impl ? ` · 实现口径 ${full.forecast.impl}` : ''}
        </p>}
      </div>}
      {leaf.route === 1 && <p className="table-note">
        路线 1 为报告预测章采用的图（{leaf.rows.length} 个学科）；路线 2 在下一页。
      </p>}
    </Leaf>
  }
  return <Leaf book={book} n={n}>
    <div className="end-page">
      <span className="end-emblem" aria-hidden="true">雲</span>
      <h2>阅毕归架</h2>
      <p>{book.full
        ? '本册开放本期报告全内容：指标、学科大表、顶尖论文与双路线预测。'
        : '本册开放封面、目录与名词解释。'}</p>
      <div className="end-rule" aria-hidden="true" />
      <strong>云南大学图书馆<br />学科情报特藏</strong>
      <small>YUNNAN UNIVERSITY LIBRARY</small>
    </div>
  </Leaf>
}

/** 文字版：屏幕阅读器与翻页组件加载失败时都能完整读到册页内容。 */
function ReadableSections({ book }: { book: ShelfBook }) {
  const full = book.full
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
    {!!full?.report_text?.length && (
      <section>
        <h3>报告正文</h3>
        {full.report_text.map((b, i) => b.t === 'h1' ? <h4 key={i}>{b.text}</h4>
          : b.t === 'h2' ? <h5 key={i}>{b.text}</h5>
          : b.t === 'p' ? <p key={i}>{b.text}</p>
          : b.t === 'tbl' ? <table key={i}><tbody>
            {b.rows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{cell.text || '（图）'}</td>)}</tr>)}
          </tbody></table>
          : <p key={i}>（图）</p>)}
      </section>
    )}
    {full && <>
      <section>
        <h3>数字体检</h3>
        <p>断言通过 {full.n_assert_pass ?? '—'}/{full.n_assert_total ?? '—'} · 覆盖窗口 {full.coverage || '—'}</p>
      </section>
      <section>
        <h3>本期指标</h3>
        <p>国际排名 {full.rank_intl_now ?? '—'} · 国内高校排名 {full.rank_cn_uni_now ?? '—'} ·
          前 1% 学科 {full.n_disc_1pct ?? '—'} · 顶尖论文 {full.top_papers_now ?? '—'}</p>
      </section>
      <section>
        <h3>学科大表</h3>
        <table>
          <thead><tr><th>学科</th><th>论文</th><th>被引</th><th>CNCI</th><th>顶尖</th><th>接近度</th><th>位次</th></tr></thead>
          <tbody>
            {(full.table ?? []).map((row) => <tr key={`${row.en}-${row.cn}`}>
              <td>{row.cn || row.en}</td><td>{row.papers ?? '—'}</td><td>{row.cites ?? '—'}</td>
              <td>{typeof row.cnci === 'number' ? row.cnci.toFixed(2) : '—'}</td>
              <td>{row.top ?? '—'}</td><td>{row.prox || '—'}</td><td>{row.rank || '—'}</td>
            </tr>)}
          </tbody>
        </table>
      </section>
      <section>
        <h3>双路线预测</h3>
        <p>路线 1（总被引 / 前 1% 阈值）：{full.forecast?.rows?.length ?? 0} 个学科；
          路线 2（国内排名 / 前 1% 机构数）：{full.forecast?.rows2?.length ?? 0} 个学科。</p>
        {full.forecast?.window && <p>序列窗口 {full.forecast.window}。</p>}
      </section>
    </>}
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
          maxWidth: 780,
          minHeight: 400,
          maxHeight: 1080,
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
        // 起始页在装载时已定位（如从名词解释直接进入）；翻页只留声音反馈。
        instance.on('flip', () => {
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

  return <section className="site stage-reader">
    <div className="scene-wrap" aria-hidden="true">
      <div className="reading-backdrop" />
    </div>

    <div className="grain" aria-hidden="true" />

    <header className="topbar">
      <button className="brand" type="button" onClick={onBackHome} aria-label="返回云南大学图书馆首页">
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
      学科信息参考 · {book.cover[2]} 馆藏阅览
    </h2>

    <div className="reader flip-reader">
      {/* 归架＝关闭（同一个动作），合并成一个浮层按钮；腾出的纵向空间全给书 */}
      <button className="reader-exit" type="button" onClick={onClose}>← 归架</button>

      <div className="reading-area flip-reading-area">
        <div className="flip-wrap" ref={wrapRef}>
          {flipError && <div className="flip-fallback">
            <strong>翻页组件没有加载成功，先以文字版显示本册内容。</strong>
            <ReadableSections book={book} />
          </div>}
        </div>
      </div>

      <p className="reader-hint flip-hint" aria-hidden="true">
        点击书页或拖动页角翻页 · ← → 键翻页 · 左上「归架」退出
      </p>

      <div className="flip-page-templates" ref={templatesRef} aria-hidden="true">
        {leaves.map((leaf, index) => <article
          key={`${book.cover[2]}-${index}`}
          className="flip-page"
          data-density={index === 0 || index === pageCount - 1 ? 'hard' : 'soft'}
        >
          <div className="flip-page-shell">{leafContent(book, leaf, index)}</div>
        </article>)}
      </div>
    </div>

    <div className="reader-sr-only" role="region" aria-label="安全预览文字版">
      <ReadableSections book={book} />
    </div>
  </section>
}
