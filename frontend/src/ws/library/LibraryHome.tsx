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
function volX(idx: number, n: number) {
  const step = Math.min(13.7, 68.2 / Math.max(1, n - 1))
  return `${(16.8 + idx * step).toFixed(1)}%`
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
  latest?: boolean
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
   最新一期即素材封面上的原印期号，往期封面需叠期号铭牌盖住烧死的「202609」 */
function buildVols(books: ShelfBook[]): Vol[] {
  const vols = [...books]
    .sort((a, b) => (b.period ?? '').localeCompare(a.period ?? ''))
    .map(toVol)
    .filter((v): v is Vol => v !== null)
  if (vols.length) vols[0] = { ...vols[0], latest: true }
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

export default function LibraryHome({ books, stats }: LibraryHomeProps) {
  const vols = useMemo(() => buildVols(books), [books])
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
    document.title = '文衡 · 学科情报阅览室'
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

  /* 深链 #v-202607：期次存在则直接进详情 */
  useEffect(() => {
    const m = /^#v-(\d{6})$/.exec(window.location.hash || '')
    if (!m) return
    if (!vols.some((v) => v.period === m[1])) return
    openDetail(m[1])
  }, [vols, openDetail])

  const frameSrc = detail.open ? `/app/shelf/pages.html#issue-${detail.period}` : 'about:blank'

  return (
    <>
      <header className="brand">
        <svg className="mk" viewBox="0 0 28 38" fill="none" stroke="currentColor" aria-hidden="true">
          <path d="M4 3h20v32H4zM8 7h12v24H8zM11 10v18M17 10v18M8 19h12" strokeWidth="1.2" />
          <path d="m11 14 3 5 3-5" strokeWidth="1.2" />
        </svg>
        <div className="brand-txt"><b>文衡 · 陈列馆</b><span>学科情报阅览室</span></div>
      </header>
      <span className="index" aria-hidden="true">YUNNAN UNIVERSITY LIBRARY / A–01</span>

      {/* 首屏 · 书架 */}
      <section className="shelf-view">
        <div className="headline">
          <h1>一年六期，一期一册。</h1>
          <p>云南大学图书馆 · 学科信息参考 · 2026 年馆藏</p>
        </div>
        <div className="shelf" id="shelf" aria-label="2026 年馆藏，共五册">
          {/* 新书期次待装帧：DESIGN_MAP 查不到封面时用深绿底期号占位（样式见 shelf-landing.css）。
              往期册封面叠期号铭牌：素材图里印的是当期号，铭牌盖住并印正确期号/月份 */}
          {vols.map((v, i) => {
            const style: CSSProperties & { '--x': string } = { '--x': volX(i, vols.length) }
            return (
              <a key={v.period} className="vol" href={`#v-${v.period}`} style={style}
                 aria-label={`${v.period}，${v.issue}，${designLabel(v.design)}`}
                 onClick={(e) => { e.preventDefault(); openDetail(v.period) }}>
                {v.cover
                  ? <img className="face" src={`/app/shelf/assets/wenheng-covers/${v.cover}`}
                         alt={`学科信息参考 ${v.issue}，${v.design}装帧封面`} draggable={false} />
                  : <span className="face placeholder" aria-hidden="true"><b>{v.period}</b>待装帧</span>}
                {v.cover && !v.latest && (
                  <span className="reissue" aria-hidden="true">
                    <span className="re-mask" />
                    <b className="re-num">{v.period}</b>
                    <i className="re-date">{v.month}</i>
                  </span>
                )}
                <span className="cap"><b>{v.period}</b>{designLabel(v.design)}</span>
              </a>
            )
          })}
        </div>
        <p className="down">向 下 滚 动 · 逐 期 册 页</p>
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
              <figure className="shot"><img src="/app/shelf/assets/shots/01-取数核验.png" alt="取数核验" loading="lazy" /></figure>
              <div className="txt"><h3>一期数据，一次取齐。</h3>
                <p>机器跑的那一步叫「取数」，人核对的那一步叫「取数核验」。两步合成一屏，屏题就是步骤名。</p>
                <p>缺哪张表、哪一列，逐条写明，补上重跑。</p>
                <p className="metric">{fmt(stats?.monitored)} 个学科在监测 ｜ {fmt(stats?.topOnePercent)} 个已进 ESI 全球前 1%</p></div>
            </article>

            <article className="stn flip">
              <figure className="shot"><img src="/app/shelf/assets/shots/03-预测选模.png" alt="预测选模" loading="lazy" /></figure>
              <div className="txt"><h3>潜力学科，先算接近度，再选模型。</h3>
                <p>每个学科到前 1% 还有多远，是「接近度」。按接近度排开，谁先到、谁还远，一屏看完。</p>
                <p>模型逐科选，选完才落到下一站。</p>
                <p className="metric">{fmt(stats?.highlyCited)} 篇热点／高被引 ｜ 逐 学 科 择 模</p></div>
            </article>

            <article className="stn">
              <figure className="shot"><img src="/app/shelf/assets/shots/04-生成初稿.png" alt="生成初稿" loading="lazy" /></figure>
              <div className="txt"><h3>约 20 秒，排出一版可读的稿子。</h3>
                <p>19 张台账表是全部数字的源头。报告里 {fmt(stats?.docSlots)} 个数字，{fmt(stats?.docSlots)} 个标了出处——点得回那一格。</p>
                <p>数字只有一个源头，稿子不在前端算任何一个数。</p>
                <p className="metric">约 20 秒 ｜ 19 张表 ｜ {fmt(stats?.docSlots)} 处出处</p></div>
            </article>

            <article className="stn flip">
              <figure className="shot"><img src="/app/shelf/assets/shots/05-核验定稿.png" alt="核验定稿" loading="lazy" /></figure>
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
          <LibraryPano books={books} />
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
        <div className="warn">陳 列 館 只 出 封 面 / 目 錄 / 名 詞 解 釋</div>
      </footer>

      {/* 点书后：原样载入连续册页（2026-10-25 rick 裁定：去掉「← 回书架」按钮，
          关闭走 iframe 内左栏 ← / 品牌点击的 postMessage 或 Escape） */}
      <div className="detail-frame" hidden={!detail.open}>
        <iframe id="detailIframe" title="单册详情" referrerPolicy="no-referrer" src={frameSrc} />
      </div>
    </>
  )
}
