/* 陈列馆首页 —— 按 web/mockups/陈列馆-完整（静态稿 20261025）.html 的 HTML 骨架 React 化
   （2026-10-25 rick 钦定：结构/文案/交互与静态稿逐一对齐，只做工程转译）。
   书架/四站/边界/问文衡/关于的文案为申报口径，一字未改；
   事实数字由 preview.js stats 供给（缺省显示 —）；「19 张表」「约 20 秒」无产物口径，保留硬编码。
   点书后原样载入连续册页 /app/shelf/pages.html（iframe 层），关闭路径两条：
   Escape / iframe 内左栏 ← 或品牌点击 postMessage('backToShelf')；另支持 #v-期次 深链。
   书架往期册封面由素材图叠「期号铭牌」（.reissue，比例照连续册页稿 cp-*）盖住素材内
   烧死的当期号——2026-10-25 rick 裁定解决素材期号债。 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import type { ShelfBook, ShelfStats } from './types'
import LibraryPano from './LibraryPano'
import './shelf-landing.css'

type LibraryHomeProps = {
  books: ShelfBook[]
  stats?: ShelfStats
  /** 排期里已建、还没出稿的期次；在书架末位补占位（2026-10-26 方案 C） */
  pendingPeriods?: string[]
}

/* 装帧映射（静态半边，硬编码自静态稿 BOOKS）：期次 → 装帧名 / 封面文件。
   书架 x 位不再逐册写死——volX() 按册数均分搁板（n=5 时输出与静态稿逐字一致，
   将来加册自动收紧步长，2026-10-25 rick 裁定解决容量债）；
   动态半边（期号 / 总期数）由后端 cover[2] 解析，月份由 period 导出；
   查不到的将来期次回落「待装帧」——书架条目照渲染，无封面用占位（见 shelf-landing.css）。 */
const DESIGN_MAP: Record<string, { design: string; cover: string }> = {
  '202609': { design: '会泽院', cover: 'huizeyuan.webp' },
  '202607': { design: '至公堂', cover: 'zhigongtang.webp' },
  '202605': { design: '银杏', cover: 'yinxing.webp' },
  '202603': { design: '阅览室', cover: 'yuelanshi.webp' },
  '202601': { design: '校门', cover: 'xiaomen.webp' },
}

/* 静态稿五册 x＝16.8% 起步、步长 13.7%；板右缘约 85%，超出五册时按剩余空间收紧步长 */
/* 书架排布（2026-10-26 方案 C 重写）：改为「按总宽居中」。
   旧法固定 16.8% 起、步长 13.7%，加册只压步长、压到 0 就叠——当期抬高后书更宽，
   旧法必然压到下一册。新法：先按标准间距累加总宽，再整体居中。
   n=5 无当期抬高时输出与旧法几乎一致（16.7 / 30.4 / 44.2 / 57.9 / 71.6），
   当期抬高时靠自身宽度自然让位，6 册（含待装帧）时向两侧摊平。 */
const H_STD = 24.9 // 与 .vol 的 height 一致
const H_FEATURED = 30.4 // 与 .vol.is-featured 的 height 一致
/** 书架高宽比 1600/1067 × 书封 210/297：把「高度百分比」换算成「宽度百分比」 */
const W_RATIO = (1067 / 1600) * (210 / 297)
const W_STD = H_STD * W_RATIO
const W_FEATURED = H_FEATURED * W_RATIO
const GAP = 1.96 // 标准间距（%），沿用旧法的步长 13.7 − 书宽 11.74

function volLayout(n: number, featuredIdx: number): string[] {
  if (n <= 0) return []
  const widths = Array.from({ length: n }, (_, i) => (i === featuredIdx ? W_FEATURED : W_STD))
  const total = widths.reduce((a, b) => a + b, 0) + GAP * (n - 1)
  let x = Math.max(2, (100 - total) / 2)
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    out.push(`${x.toFixed(1)}%`)
    x += widths[i] + GAP
  }
  return out
}

/* cover[2] 形如「2026年第5期（总第39期）」 */
const ISSUE_RE = /(\d{4})年第(\d+)期（总第(\d+)期）/

type Vol = {
  period: string
  issue: string
  month: string
  total?: number
  design: string
  cover?: string
  /** 书架最靠前的那一册（当期）：抬高、金线、书目行加金色期号 */
  featured?: boolean
  /** 排期已建、还没出稿的末位空格（无封面、不可点） */
  pending?: boolean
}

function toVol(book: ShelfBook): Vol | null {
  const period = book.period
  if (!period) return null
  const m = ISSUE_RE.exec(book.cover[2] ?? '')
  const issue = m ? `${m[1]} 年第 ${Number(m[2])} 期` : (book.cover[2] ?? '')
  const total = m ? Number(m[3]) : undefined
  const monthNum = period.length >= 6 ? Number(period.slice(4, 6)) : Number.NaN
  const month = monthNum >= 1 && monthNum <= 12 ? `${period.slice(0, 4)} 年 ${monthNum} 月` : ''
  const mapped = DESIGN_MAP[period]
  return {
    period, issue, month, total,
    design: mapped?.design ?? '待装帧',
    ...(mapped ? { cover: mapped.cover } : {}),
  }
}

/* 书架按新 → 旧排（books 到手是期次升序；按期次倒排，等价于静态稿 BOOKS 的顺序）；
   最新一期即素材封面上的原印期号，往期封面需叠期号铭牌盖住烧死的「202609」。
   2026-10-26 方案 C：末位补「待装帧」空格（排期已建、未出稿的期次，由 data.ts 供给），
   并把排在最前的那一册标成 featured——首屏有主次，不再五册同级。
   「待装帧」只认排期表，不从上一期推月份：推出来的期次是编的。 */
function buildVols(books: ShelfBook[], pending: string[] = []): Vol[] {
  const vols = [...books]
    .sort((a, b) => (b.period ?? '').localeCompare(a.period ?? ''))
    .map(toVol)
    .filter((v): v is Vol => v !== null)
  for (const period of pending) {
    if (vols.some((v) => v.period === period)) continue
    vols.push({ period, issue: '', month: '', design: '待装帧', pending: true })
  }
  const firstReal = vols.findIndex((v) => !v.pending)
  if (firstReal >= 0) vols[firstReal] = { ...vols[firstReal], featured: true }
  return vols
}

function designLabel(design: string) {
  return design === '待装帧' ? design : `${design}装帧`
}

function fmt(n?: number) {
  return n === undefined ? '—' : String(n)
}

type DetailState = { open: boolean; period: string }
const DETAIL_CLOSED: DetailState = { open: false, period: '' }

export default function LibraryHome({ books, stats, pendingPeriods }: LibraryHomeProps) {
  const vols = useMemo(() => buildVols(books, pendingPeriods ?? []), [books, pendingPeriods])
  /* 排布一次算好：当期下标决定每册多宽，宽度又决定后面每一册的起点 */
  const xs = useMemo(() => volLayout(vols.length, vols.findIndex((v) => v.featured)), [vols])
  const realCount = vols.filter((v) => !v.pending).length
  const [detail, setDetail] = useState<DetailState>(DETAIL_CLOSED)

  /* 「連 續 記 錄 · N 期」的 N：取各册 cover[2] 解析出的总期数最大值 */
  let maxTotal: number | undefined
  for (const v of vols) {
    if (v.total !== undefined && (maxTotal === undefined || v.total > maxTotal)) maxTotal = v.total
  }

  const openDetail = useCallback((period: string) => {
    setDetail({ open: true, period })
    document.title = `学科信息参考 ${period} · 文衡`
  }, [])

  const closeDetail = useCallback(() => {
    setDetail(DETAIL_CLOSED)
    document.title = '文衡 · 陈列馆'
    window.scrollTo(0, 0)
  }, [])

  /* 详情打开期间锁 body 滚动；三条关闭路径里 Escape / postMessage 在此监听 */
  useEffect(() => {
    if (!detail.open) return
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeDetail() }
    const onMsg = (e: MessageEvent) => { if (e.data === 'backToShelf') closeDetail() }
    window.addEventListener('keydown', onKey)
    window.addEventListener('message', onMsg)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('message', onMsg)
    }
  }, [detail.open, closeDetail])

  /* 深链 #v-202607：期次存在则直接进详情。
     2026-10-26 补 hashchange：此前只在首次挂载读一次 hash，页内由外部链接改 hash 不响应。 */
  useEffect(() => {
    const apply = () => {
      const m = /^#v-(\d{6})$/.exec(window.location.hash || '')
      if (!m) return
      if (!vols.some((v) => v.period === m[1])) return
      openDetail(m[1])
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [vols, openDetail])

  const frameSrc = detail.open ? `/app/shelf/pages.html#issue-${detail.period}` : 'about:blank'

  return (
    <>
      <header className="brand">
        <svg className="mk" viewBox="0 0 28 38" fill="none" stroke="currentColor" aria-hidden="true">
          <path d="M4 3h20v32H4zM8 7h12v24H8zM11 10v18M17 10v18M8 19h12" strokeWidth="1.2" />
          <path d="m11 14 3 5 3-5" strokeWidth="1.2" />
        </svg>
        <div className="brand-txt"><b>文衡 · 陈列馆</b><span>云南大学图书馆</span></div>
      </header>

      {/* 首屏 · 书架 */}
      <section className="shelf-view">
        <div className="headline">
          <h1>一年六期，一期一册。</h1>
          <p>云南大学图书馆 · 学科信息参考 · 2026 年馆藏</p>
        </div>
        <div className="shelf" id="shelf" aria-label={`2026 年馆藏，共 ${realCount} 册`}>
          {/* 新书期次待装帧：DESIGN_MAP 查不到封面时用深绿底期号占位（样式见 shelf-landing.css）。
              往期册封面叠期号铭牌：素材图里印的是当期号，铭牌盖住并印正确期号/月份 */}
          {vols.map((v, i) => {
            const style: CSSProperties & { '--x': string } = { '--x': xs[i] ?? '16.8%' }
            const tone = v.featured ? ' is-featured' : ' is-sub'
            /* 待装帧：不是书，不可点、不进 Tab 序，也不给 hover 书目行（面上已写期号与「待装帧」） */
            if (v.pending) {
              return (
                <span key={v.period} className={`vol${tone} is-pending`} style={style}
                      aria-label={`${v.period}，待装帧`}>
                  <span className="face placeholder" aria-hidden="true"><b>{v.period}</b>待装帧</span>
                </span>
              )
            }
            return (
              <a key={v.period} className={`vol${tone}`} href={`#v-${v.period}`} style={style}
                 aria-label={`${v.period}，${v.issue}，${designLabel(v.design)}`}
                 onClick={(e) => { e.preventDefault(); openDetail(v.period) }}>
                {v.cover
                  ? <img className="face" src={`/app/shelf/assets/wenheng-covers/${v.cover}`}
                         alt={`学科信息参考 ${v.issue}，${v.design}装帧封面`} draggable={false} />
                  : <span className="face placeholder" aria-hidden="true"><b>{v.period}</b>待装帧</span>}
                {/* 期号铭牌：六册一律叠（2026-10-26 方案 C）。原来只有往期叠，
                    结果当期用素材原印的小字、往期反倒有大铭牌——主次倒挂。
                    当期那册烧的就是对的期号，盖上再印同一个号，观感反而统一。 */}
                {v.cover && (
                  <span className="reissue" aria-hidden="true">
                    <span className="re-mask" />
                    <b className="re-num">{v.period}</b>
                  </span>
                )}
                <span className="cap"><b>{v.period}</b>{designLabel(v.design)}<em>{v.month}</em></span>
              </a>
            )
          })}
          {/* 滚动提示：2026-10-26 从 section 底部挪进书架内部，按托板线定位（见 shelf-landing.css .down） */}
          <p className="down">向 下 滚 动 · 逐 期 册 页</p>
        </div>
        {/* 角落编号：2026-10-26 收进 .shelf-view 内。原来挂在外层，
            绝对定位落到「初始包含块」的底部＝视口底，落点在木色/纸色之间随视口漂，
            实测 1366 上压在中灰木纹上只有 2.0:1。收进来后固定在首屏右下（纸色区）。 */}
        <span className="index" aria-hidden="true">YUNNAN UNIVERSITY LIBRARY / A–01</span>
      </section>

      {/* 册页：静态稿主流程不逐期展开——期次/目录/口径在 pages.html 的连续册页里 */}
      {/* 事实数字由 preview.js stats 供给（缺省 —）；「19 张表」「约 20 秒」无产物口径保留硬编码 */}
      <main className="flow" id="flow">
        {/* 四站 */}
        <section className="sec" id="how">
          <div className="wrap">
            <h2 className="sec-title">一期一册，<br />是这么来的。</h2>
            <p className="deck">四站走完，才允许装帧。每一步都留痕，每一步都能回去看。</p>

            <article className="stn">
              <figure className="shot"><img src="/app/shelf/assets/shots/01-取数核验.webp" alt="取数核验" loading="lazy" /></figure>
              <div className="txt"><h3>一期数据，一次取齐。</h3>
                <p>机器跑的那一步叫「取数」，人核对的那一步叫「取数核验」。两步合成一屏，屏题就是步骤名。</p>
                <p>缺哪张表、哪一列，逐条写明，补上重跑。</p>
                <p className="metric">{fmt(stats?.monitored)} 个学科在监测 ｜ {fmt(stats?.topOnePercent)} 个已进 ESI 全球前 1%</p></div>
            </article>

            <article className="stn flip">
              <figure className="shot"><img src="/app/shelf/assets/shots/03-预测选模.webp" alt="预测选模" loading="lazy" /></figure>
              <div className="txt"><h3>潜力学科，先算接近度，再选模型。</h3>
                <p>每个学科到前 1% 还有多远，是「接近度」。按接近度排开，谁先到、谁还远，一屏看完。</p>
                <p>模型逐科选，选完才落到下一站。</p>
                <p className="metric">{fmt(stats?.highlyCited)} 篇热点／高被引 ｜ 逐 学 科 择 模</p></div>
            </article>

            <article className="stn">
              <figure className="shot"><img src="/app/shelf/assets/shots/04-生成初稿.webp" alt="生成初稿" loading="lazy" /></figure>
              <div className="txt"><h3>约 20 秒，排出一版可读的稿子。</h3>
                <p>19 张台账表是全部数字的源头。报告里 {fmt(stats?.docSlots)} 个数字，{fmt(stats?.docSlots)} 个标了出处——点得回那一格。</p>
                <p>数字只有一个源头，稿子不在前端算任何一个数。</p>
                <p className="metric">约 20 秒 ｜ 19 张表 ｜ {fmt(stats?.docSlots)} 处出处</p></div>
            </article>

            <article className="stn flip">
              <figure className="shot"><img src="/app/shelf/assets/shots/05-核验定稿.webp" alt="核验定稿" loading="lazy" /></figure>
              <div className="txt"><h3>机器保数字，取舍你来定。</h3>
                <p>出稿前机器逐项自检——{fmt(stats?.selfChecks)} 项核对，全部通过才交到你手上。剩下的 {fmt(stats?.pendingManual)} 处待人工，逐条看着补。</p>
                <p>复核无异议才签单，签了才签发。</p>
                <p className="metric">{fmt(stats?.selfChecks)} 项核对 ｜ {fmt(stats?.pendingManual)} 处待人工</p></div>
            </article>
          </div>
        </section>

        {/* 产线全景（回放态）——rick 2026-10-26：可视化工作流放到书架下面。
            四站图文讲完「是这么来的」，这里直接看真产线；实时运行态在工作区。
            申报口径四站文案在上一段，一字未动。 */}
        <section className="sec" id="pano">
          <div className="wrap"><LibraryPano books={books} /></div>
        </section>

        {/* 边界 */}
        <section className="sec" id="boundary">
          <div className="wrap bnd">
            <div>
              <h2 className="sec-title">看得见的边界</h2>
              <p className="deck">陈列馆只开放三样内容。要看正文与数值，<a href="/app/?period=202609">进工作区</a>——那里每一步都留痕。</p>
            </div>
            <div className="bndbox">
              <div className="h">館 藏 閱 讀 範 圍</div>
              <ul>
                <li><span className="m" />封 面</li>
                <li><span className="m" />目 錄</li>
                <li><span className="m" />名 詞 解 釋</li>
                <li className="no"><span className="m" />正 文 數 值　不出館</li>
                <li className="no"><span className="m" />運 行 檔 案　不出館</li>
                <li className="no"><span className="m" />台 賬 原 件　不出館</li>
              </ul>
            </div>
          </div>
        </section>

        {/* 问文衡 */}
        <section className="sec ask" id="ask">
          <div className="wrap askgrid">
            <div>
              <h2 className="sec-title">问文衡</h2>
              <p className="deck">工作台里能查的，这里都能问。先问一句，点进去接着聊。</p>
            </div>
            <div>
              <form className="askform" action="/app/dialog/" method="get">
                <label className="sr-only" htmlFor="q">问文衡</label>
                <input id="q" name="ask" type="text" autoComplete="off" placeholder="问一句：某学科的接近度是多少" />
                <button type="submit">去 问 文 衡 ↖</button>
              </form>
              <div className="chips">
                <span className="lb">试 问</span>
                <a href="/app/dialog/?ask=某一学科的接近度是多少">某一学科的接近度是多少</a>
                <a href="/app/dialog/?ask=云南大学什么时候能进前%201%25">云南大学什么时候能进前 1%</a>
                <a href="/app/dialog/?ask=这期做了没有">这期做了没有</a>
              </div>
            </div>
          </div>
        </section>

        {/* 关于 */}
        <section className="sec about" id="about">
          <div className="wrap about-grid">
            <div>
              <h2 className="sec-title">关于本册</h2>
              <p className="deck">《学科信息参考》是云南大学图书馆的双月刊。每期取数、核对、出稿、签发，一步一步留痕，再装帧成册，陈列于此。</p>
              <p className="deck">馆藏位置　学科情报馆藏 A 区 01　·　<a href="/app/?period=202609">回 工 作 台 ↖</a></p>
            </div>
            <div className="facts">
              <div className="f"><div className="k">學 科 監 測</div><div className="v">{fmt(stats?.monitored)}</div></div>
              <div className="f"><div className="k">已 進 前 1 %</div><div className="v">{fmt(stats?.topOnePercent)}</div></div>
              <div className="f"><div className="k">連 續 記 錄</div><div className="v sm">2019 年起 · {fmt(maxTotal)} 期</div></div>
              <div className="f"><div className="k">上 榜 論 文</div><div className="v">{fmt(stats?.highlyCited)}</div></div>
            </div>
          </div>
        </section>
      </main>

      <footer className="foot">
        <div><b>文衡 · 陈列馆</b>　雲 南 大 學 圖 書 館 · 學 科 信 息 參 考</div>
        <div className="links">
          <a href="/app/shelf/">陈列馆</a>
          <a href="/app/?period=202609">回工作台</a>
          <a href="/app/dialog/">问文衡</a>
        </div>
        <div>逐 期 裝 幀　·　A 区 01</div>
      </footer>

      {/* 点书后：原样载入连续册页（2026-10-25 rick 裁定：去掉「← 回书架」按钮，
          关闭走 iframe 内左栏 ← / 品牌点击的 postMessage 或 Escape） */}
      <div className="detail-frame" hidden={!detail.open}>
        <iframe id="detailIframe" title="单册详情" referrerPolicy="no-referrer" src={frameSrc} />
      </div>
    </>
  )
}
