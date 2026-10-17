/* 陈列馆单页（2026-10-17 rick 拍板，据 web/mockups/陈列馆-优化.html 落地）：
   就这一页；馆藏书封点击进翻书器（音效在 ShelfPage/Reader 管，保留）；3D 退役不出入口。
   数字与目录只透传后端（books），流程词表与工作台 UX.md §十 同词同义。 */

import type { ShelfBook } from './types'
import type { ReaderSection } from './Reader'
import './shelf-landing.css'
import heroPhoto from './assets/ynu-library-real.png'

type LibraryHomeProps = {
  books: ShelfBook[]
  backToWorkspace?: boolean
  onEnterExterior: () => void
  onOpenBook: (bookIndex: number, section: ReaderSection, trigger: HTMLButtonElement) => void
}

const TERMS: { term: string; tag: string; mac?: boolean; def: string; use: string }[] = [
  { term: '取数', tag: '机器 进度', mac: true, def: '把当期的原始数据取回来。机器跑的那一步叫「取数」，人核对的那一步叫「取数核验」。', use: '两步合成一屏，屏题就是步骤名' },
  { term: '一键生成', tag: '机器 进度', mac: true, def: '机器把稿子排出来。人的那一步叫「生成初稿」——先看一遍，再交给复核。', use: '状态词不参与命名，只管叫这一个名' },
  { term: '五 站 五 屏', tag: '流程', def: '一期从头到尾走五步：取数核验、选章节、预测选模、生成初稿、核验定稿。一步一屏，不多不少。', use: '屏幕标题就是站名，不另起新名' },
  { term: '签单', tag: '动作', def: '复核无异议后，签下这一版的动作。签了，才轮到下面那个词。', use: '动作叫签单，状态叫签发，别混用' },
  { term: '签发', tag: '状态', def: '这一版的处境，只有三种：未签发、已签发、签发已失效。签发前不能下载初稿。', use: '「签名」只指数字签名时才出现' },
  { term: '任务', tag: '状态', def: '这期做没做完，只有三种：进行中、已完成、未开始。', use: '任务与签发，全站就这两套状态词' },
]

export default function LibraryHome({ books, onOpenBook, backToWorkspace }: LibraryHomeProps) {
  const latest = books[0]
  return (
    <div className="sl-page">
      {/* 顶栏 */}
      <header className="sl-top">
        <a className="wm" href="#home"><b>云大 W</b><span>圖 書 館<br />YUNNAN UNIVERSITY LIBRARY</span></a>
        <nav aria-label="陈列馆导航">
          <a className="on" href="#home">首页</a>
          <a href="#bookshelf">馆藏</a>
          <a href="#disciplines">学科概览</a>
          <a href="#collection">内容导读</a>
          <a href="#about">关于本册</a>
        </nav>
        <a className="back sl-back" href="/app/dialog/">回 问 文 衡 ↖</a>
        {backToWorkspace && <a className="back" href="/app/">回 工 作 台 ↖</a>}
      </header>

      {/* ① 首页 */}
      <section className="home-hero" id="home">
        <img className="photo" src={heroPhoto} alt="云南大学呈贡校区图书馆，入馆台阶与双翼楼体、门前广场" />
        <div className="scrim" aria-hidden="true" />
        <div className="in">
          <div className="kicker">雲 南 大 學 圖 書 館 · 學 科 情 報 平 台 的 門 面</div>
          <h1>云南大学<br /><em>图书馆</em></h1>
          <p className="sub">学科信息参考 · 呈贡馆藏 · 逐册装帧。这里陈列的是每一期成刊，一册一册，循流而上。</p>
          <p className="facts"><b>22</b> 个学科在监测 · <b>14</b> 个已进 ESI 全球前 1% · <b>2019</b> 年起 <b>39</b> 期连续记录 · <b>291</b> 篇热点／高被引上榜</p>
          <div className="acts">
            <button type="button" className="sl-btn" onClick={() => document.getElementById('bookshelf')?.scrollIntoView({ behavior: 'smooth' })}>走 进 馆 藏 →</button>
            <button type="button" className="sl-ghost" onClick={() => document.getElementById('disciplines')?.scrollIntoView({ behavior: 'smooth' })}>学科速览</button>
          </div>
        </div>
        <div className="cap"><b>呈贡校区 · 图书馆</b>云大馆侧、呈贡新馆中庭</div>
      </section>

      {/* 记录条 */}
      <div className="sl-strip">
        <span><b>学科情报记录</b>　DISCIPLINE INTELLIGENCE</span>
        <span>逐 期 裝 幀　·　只 出 封 面 / 目 錄 / 名 詞 解 釋</span>
      </div>

      {/* ② 问文衡 */}
      <section className="sl-ask" id="ask">
        <div className="sl-ct grid">
          <div>
            <div className="sl-kik">ASK WENHENG</div>
            <h2>问文衡</h2>
            <p className="deck">工作台里能查的，这里都能问。<br />先问一句，点进去接着聊。</p>
          </div>
          <div>
            <form className="sl-askform" onSubmit={(e) => {
              e.preventDefault()
              const q = new FormData(e.currentTarget).get('q')
              window.location.href = `/app/dialog/${q ? `?ask=${encodeURIComponent(String(q))}` : ''}`
            }}>
              <input name="q" aria-label="问文衡" placeholder="问一句：某学科的接近度是多少" />
              <button type="submit">去 问 文 衡 ↖</button>
            </form>
            <div className="sl-chips">
              <span className="lb">试 问</span>
              <a href="/app/dialog/?ask=某一学科的接近度是多少">某一学科的接近度是多少</a>
              <a href="/app/dialog/?ask=云南大学什么时候能进前%201%25">云南大学什么时候能进前 1%</a>
              <a href="/app/dialog/?ask=这期做了没有">这期做了没有</a>
            </div>
          </div>
        </div>
      </section>

      {/* ③ 阅览室 */}
      <section className="sl-room" id="collection">
        <div className="sl-ct">
          <div className="sl-sec-h">
            <div>
              <div className="sl-kik">THE READING ROOM</div>
              <h2>一册一册，循流而上。</h2>
            </div>
            <p className="note">每期成刊，只在读者看得见的边界里陈列。看正文，进工作区。</p>
          </div>
          <div className="sl-feats">
            <article className="sl-ft">
              <div className="ic" aria-hidden="true"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="4" y="5" width="26" height="24" /><line x1="4" y1="11" x2="30" y2="11" /><line x1="10" y1="17" x2="24" y2="17" /><line x1="10" y1="22" x2="20" y2="22" /></svg></div>
              <div className="t">逐期成刊</div>
              <div className="d">一期一册，装帧统一。册子排在架上，一眼认得出是哪一期。</div>
            </article>
            <article className="sl-ft">
              <div className="ic" aria-hidden="true"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M17 4 30 10v14L17 30 4 24V10z" /><path d="M4 10l13 6 13-6M17 16v14" /></svg></div>
              <div className="t">只出三样</div>
              <div className="d">封面、目录、名词解释。正文数值不出馆，看得见的是边界。</div>
            </article>
            <article className="sl-ft">
              <div className="ic" aria-hidden="true"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="5" y="4" width="18" height="26" /><path d="M23 10h6v20H11" /><line x1="10" y1="11" x2="18" y2="11" /><line x1="10" y1="16" x2="18" y2="16" /></svg></div>
              <div className="t">问文衡</div>
              <div className="d">工作台里能查的，这里都能问。一句话进对话页，接着聊。</div>
            </article>
            <article className="sl-ft">
              <div className="ic" aria-hidden="true"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="4" y1="8" x2="30" y2="8" /><line x1="4" y1="17" x2="30" y2="17" /><line x1="4" y1="26" x2="30" y2="26" /><circle cx="10" cy="8" r="1.6" /><circle cx="10" cy="17" r="1.6" /><circle cx="10" cy="26" r="1.6" /></svg></div>
              <div className="t">口径一份</div>
              <div className="d">名词解释与工作台同词同义，全站一套说法，不各说各话。</div>
            </article>
          </div>
        </div>
      </section>

      {/* ④ 馆藏：点书封进翻书器 */}
      <section className="sl-shelf" id="bookshelf">
        <div className="sl-ct">
          <div className="sl-sec-h">
            <div>
              <div className="sl-kik">COLLECTION / A 区 01</div>
              <h2>学科情报馆藏</h2>
            </div>
            <p className="note">封面只用平色与结构线，期号是锚。刊物式装帧，不做渐变金饰。点封面翻开。</p>
          </div>
          <div className="sl-books">
            {books.map((b, i) => {
              const issueNo = /总第\s*(\d+)\s*期/.exec(b.cover[2] ?? '')?.[1] ?? ''
              return (
              <div className="sl-bw" key={b.period ?? b.cover[2] ?? i}>
                <button type="button"
                        className={`sl-cover v${(i % 4) + 1}`}
                        onClick={(e) => onOpenBook(i, 'cover', e.currentTarget)}
                        aria-label={`翻开 ${b.period ?? b.cover[2] ?? ''}`}>
                  <div className="c-top"><span>雲 南 大 學</span><span>Y N U</span></div>
                  <div className="rule thick" /><div className="rule" />
                  <div className="ser">学科信息参考<br />DISCIPLINARY INFORMATION REFERENCE</div>
                  <div className="num">{b.period ?? b.cover[2] ?? ''}</div>
                  <div className="iss">{b.cover[2] ?? ''}</div>
                  <div className="bot"><span>學 科 情 報 館 藏</span><span>A 区 01</span></div>
                </button>
                <div className="sl-bmeta">
                  <div className="no">{issueNo ? `N O . ${issueNo}` : ''}</div>
                  <div className="nm">{b.period ?? ''}{b.cover[2] ? ` · ${b.cover[2]}` : ''}</div>
                  <button type="button" className="go"
                          onClick={(e) => onOpenBook(i, 'cover', e.currentTarget)}>翻 开 →</button>
                </div>
              </div>
              )
            })}
            {!books.length && <p className="note">馆藏整理中——首期成刊上架后，这里一册一册摆出来。</p>}
          </div>
          <div className="sl-shelffoot">
            <span>館 藏 位 置　<b>学科情报馆藏 A 区 01</b></span>
            <span>逐 期 裝 幀　·　只 出 封 面 / 目 錄 / 名 詞 解 釋</span>
          </div>
        </div>
      </section>

      {/* ⑤ 安全预览 */}
      <section className="sl-safe" id="archive">
        <div className="sl-ct grid">
          <div>
            <div className="sl-kik">SAFE PREVIEW</div>
            <h2>每一册馆藏，<br />都在读者看得见的边界里。</h2>
            <p className="deck">陈列馆只开放三样内容。要看正文与数值，进工作区——那里每一步都留痕。</p>
          </div>
          <div className="sl-safebox">
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

      {/* ⑥ 科目目录＋名词解释（定词表） */}
      <section className="sl-index" id="disciplines">
        <div className="sl-ct">
          <div className="sl-sec-h">
            <div>
              <div className="sl-kik">SAFE CONTENT INDEX</div>
              <h2>科目目录，只出馆藏。</h2>
            </div>
            <p className="note">名词解释与工作台同词同义。下面几条是流程用词，全站一套说法。</p>
          </div>
          <div className="sl-idx-grid">
            <div className="sl-panel sl-toc">
              <div className="panel-h"><b>目 錄</b>
                <span>{latest ? `${latest.cover[2] ?? ''} · ${(latest.period ?? '').split('').join(' ')}` : '首期上架后公布'}</span>
              </div>
              {latest?.toc?.length ? (
                <ol>
                  {latest.toc.map((t, i) => (
                    <li key={`${t.title}-${i}`}>
                      <span className="n">{String(i + 1).padStart(2, '0')}</span>
                      <span className="t">{t.title}</span>
                      <span className="p">{t.page ? `P. ${t.page}` : ''}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="note" style={{ padding: '18px 20px' }}>目录随首期成刊上架后公布。</p>
              )}
            </div>
            <div className="sl-panel sl-gl">
              <div className="panel-h"><b>名 詞 解 釋</b><span>全 站 同 詞 同 義</span></div>
              {TERMS.map((t) => (
                <div className="ent" key={t.term}>
                  <div className="term">{t.term}<span className={`tag${t.mac ? ' mac' : ''}`}>{t.tag}</span></div>
                  <div className="def">{t.def}</div>
                  <div className="use"><span className="i">i</span>{t.use}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ⑦ 关于本册 */}
      <section className="sl-about" id="about">
        <div className="sl-ct in">
          <div>
            <div className="sl-kik">ABOUT</div>
            <h2>关于本册</h2>
            <p className="deck">《学科信息参考》是云南大学图书馆的双月刊。每期取数、核对、出稿、签发，一步一步留痕，再装帧成册，陈列于此。</p>
          </div>
          <div className="sl-facts2">
            <div className="f"><div className="k">學 科 監 測</div><div className="v">22</div></div>
            <div className="f"><div className="k">已 進 前 1 %</div><div className="v">14</div></div>
            <div className="f"><div className="k">連 續 記 錄</div><div className="v sm">2019 年起 · 39 期</div></div>
            <div className="f"><div className="k">上 榜 論 文</div><div className="v">291</div></div>
          </div>
        </div>
      </section>

      {/* 页脚 */}
      <footer className="sl-foot">
        <div><b>文衡 · 陈列馆</b>　雲 南 大 學 圖 書 館 · 學 科 信 息 參 考</div>
        <div>逐 期 裝 幀　·　A 区 01</div>
        <div className="warn">陳 列 館 只 出 封 面 / 目 錄 / 名 詞 解 釋</div>
      </footer>
    </div>
  )
}
