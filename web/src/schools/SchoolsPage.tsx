/* 高校 ESI 报告 · 监测版（入口整页）。
   版面照已审静态稿 `mockups/全站静态稿-20261102/高校ESI报告-静态稿（20261102）.html`：
   左页会泽品牌面（导航逐字一致）＋ 右页报头（眉标 / 校名 / 期次）→ 总站位 → 22 行学科表；
   已入 1% 与未入之间一道 1px 金线，未在榜格子写 `—`。
   能力一件不少：院校清单（选校抽屉）、多校对比（队列）、生成报告（既有 POST 口）。
   数字零口径：总站位与学科行全部解析自后端已生成的站位报告（`/monitor/report/…`），
   前端只搬运显示值，不换算、不补数、不猜期次；后端没有的指标写 `—`。 */

import { useEffect, useRef, useState } from 'react'
import {
  type MonitorSchool, type MonitorSchools,
  generateCompareReport, generateMonitorReport, getMonitorSchools,
} from '../api-monitor'
import { HttpError } from '../api'

const RUN_STEPS = ['取数', '拼表', '出稿', '核验', '签发']

/* ESI 22 学科（固定名录；只列名字，不带任何数字）。未在榜行按英文名排序补 `—`。 */
const DISCIPLINES: { en: string; cn: string }[] = [
  { en: 'Agricultural Sciences', cn: '农业科学' },
  { en: 'Biology & Biochemistry', cn: '生物学与生物化学' },
  { en: 'Chemistry', cn: '化学' },
  { en: 'Clinical Medicine', cn: '临床医学' },
  { en: 'Computer Science', cn: '计算机科学' },
  { en: 'Economics & Business', cn: '经济与商业' },
  { en: 'Engineering', cn: '工程学' },
  { en: 'Environment/Ecology', cn: '环境生态学' },
  { en: 'Geosciences', cn: '地球科学' },
  { en: 'Immunology', cn: '免疫学' },
  { en: 'Materials Science', cn: '材料科学' },
  { en: 'Mathematics', cn: '数学' },
  { en: 'Microbiology', cn: '微生物学' },
  { en: 'Molecular Biology & Genetics', cn: '分子生物学与遗传学' },
  { en: 'Multidisciplinary', cn: '多学科' },
  { en: 'Neuroscience & Behavior', cn: '神经系统科学与行为学' },
  { en: 'Pharmacology & Toxicology', cn: '药理学与毒理学' },
  { en: 'Physics', cn: '物理学' },
  { en: 'Plant & Animal Science', cn: '植物与动物学' },
  { en: 'Psychiatry/Psychology', cn: '精神病学与心理学' },
  { en: 'Social Sciences, general', cn: '社会科学' },
  { en: 'Space Science', cn: '空间科学' },
]

type Row = { cn: string; rank: string; rankCn: string; papers: string; cites: string; per: string }
type Totals = { rank: string; rankAll: string; papers: string; cites: string; per: string }
type Standing = { rows: Row[]; totals: Totals | null }

const txt = (el: Element | null | undefined) =>
  (el?.textContent ?? '').replace(/\s+/g, ' ').trim()

/** 从后端生成的站位报告里取显示值：只读 HTML 里的成品字串，不重算。 */
function parseStanding(html: string): Standing {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const blocks = Array.from(doc.querySelectorAll('.nums .nm'))
  const block = (label: string) =>
    blocks.find((b) => txt(b.querySelector('.nl')) === label) ?? null

  let totals: Totals | null = null
  const rankBlock = block('全球机构总排名')
  const citeBlock = block('总被引')
  if (rankBlock || citeBlock) {
    const rankText = txt(rankBlock?.querySelector('.nv'))
    const [rank = '', rankAll = ''] = rankText.split('/').map((s) => s.trim())
    const nx = txt(citeBlock?.querySelector('.nx'))
    totals = {
      rank,
      rankAll,
      papers: /论文\s*([\d,]+)/.exec(nx)?.[1] ?? '—',
      cites: txt(citeBlock?.querySelector('.nv')) || '—',
      per: /篇均\s*([\d.]+)/.exec(nx)?.[1] ?? '—',
    }
  }

  const table = doc.querySelector('section.flow table')
  const rows: Row[] = Array.from(table?.querySelectorAll('tbody tr') ?? []).map((tr) => {
    const td = Array.from(tr.querySelectorAll('td'))
    const name = txt(td[0]?.querySelector('b')) || txt(td[0]).split(' ')[0]
    return {
      cn: name,
      rank: txt(td[1]).split('/')[0].trim(),
      rankCn: txt(td[3]),
      papers: txt(td[4]),
      cites: txt(td[5]),
      per: txt(td[6]),
    }
  }).filter((r) => r.cn)

  return { rows, totals }
}

/* 预开页的加载反馈：点击手势内开窗后立刻写入五步动画，生成完由本页回填报告地址；
   失败则在原页显示原因。离开这个加载页前，用户不是在盯空白。 */
function loadingDoc(label: string): string {
  const stepsJs = JSON.stringify(RUN_STEPS)
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">` +
    `<title>正在生成 · 文衡监测版</title><style>` +
    `body{margin:0;background:#F5F3EC;color:#1E2A23;font-family:system-ui,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}` +
    `.box{width:min(420px,86vw);background:#FAF8F0;border:1px solid #DFDBCB;box-shadow:0 1px 2px rgba(21,34,43,.07);padding:26px 30px}` +
    `.brand{font-family:serif;letter-spacing:.14em;font-size:14px;color:#143729}` +
    `h1{font-size:17px;margin:10px 0 2px;font-weight:600}` +
    `.sub{font-size:12px;color:#7C857B;margin:0 0 16px}` +
    `.bar{height:3px;background:#EAE7DB;margin:12px 0 8px}.fl{height:100%;width:20%;background:#1A4B27;transition:width .5s}` +
    `.step{font-size:12px;color:#1A4B27;letter-spacing:.06em}` +
    `.hint{font-size:11px;color:#7C857B;margin-top:14px;line-height:1.7}` +
    `</style></head><body><div class="box">` +
    `<div class="brand">文衡 · 高校 ESI 报告</div>` +
    `<h1>正在生成：${label}</h1>` +
    `<p class="sub">完成后本页自动跳转为报告。</p>` +
    `<div class="bar"><div class="fl" id="fl"></div></div>` +
    `<p class="step" id="st">第 1/5 步 · 取数</p>` +
    `<p class="hint">若长时间停留在此页，回本页看状态或重新生成。</p>` +
    `<script>var s=${stepsJs},i=0;setInterval(function(){i=(i+1)%s.length;document.getElementById('fl').style.width=((i+1)/s.length*100)+'%';document.getElementById('st').textContent='第 '+(i+1)+'/'+s.length+' 步 · '+s[i];},600);</script>` +
    `</div></body></html>`
}

function errDoc(msg: string): string {
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>生成失败 · 文衡监测版</title>` +
    `<style>body{margin:0;background:#F5F3EC;color:#1E2A23;font-family:system-ui,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}.box{width:min(420px,86vw);background:#FAF8F0;border:1px solid #DFDBCB;padding:26px 30px}.t{font-size:15px;font-weight:600;color:#B23A2B;margin:0 0 8px}.m{font-size:12.5px;color:#4A564D;line-height:1.8;margin:0}</style></head>` +
    `<body><div class="box"><p class="t">生成没跑成</p><p class="m">${msg}<br>回本页重试；本页可关闭。</p></div></body></html>`
}

function writeDoc(w: Window, html: string) {
  try {
    w.document.open()
    w.document.write(html)
    w.document.close()
  } catch { /* opener 已断开等场景：放弃回写，不影响主流程 */ }
}

export default function SchoolsPage() {
  const [data, setData] = useState<MonitorSchools | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [cn, setCn] = useState('')
  const [standing, setStanding] = useState<Standing | null>(null)
  const [htmlErr, setHtmlErr] = useState('')
  const [htmlBusy, setHtmlBusy] = useState(false)
  const [pickOpen, setPickOpen] = useState(false)
  const [tier, setTier] = useState<'all' | '985' | '211'>('all')
  const [q, setQ] = useState('')
  const [queue, setQueue] = useState<string[]>([])
  const [genBusy, setGenBusy] = useState('')
  const [genErr, setGenErr] = useState('')
  const [cmpBusy, setCmpBusy] = useState(false)
  const reqRef = useRef(0)
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false; reqRef.current++ }, [])

  const load = async () => {
    const id = ++reqRef.current
    setLoadErr('')
    try {
      const next = await getMonitorSchools()
      if (!aliveRef.current || id !== reqRef.current) return
      setData(next)
      setCn((cur) => cur || next.schools.find((s) => s.generated)?.cn
        || next.schools.find((s) => s.known)?.cn || next.schools[0]?.cn || '')
    } catch (e) {
      if (!aliveRef.current || id !== reqRef.current) return
      setLoadErr(e instanceof HttpError ? e.message : '院校清单没读到——确认服务在运行后重试')
    }
  }
  useEffect(() => { void load() }, [])

  const school = data?.schools.find((s) => s.cn === cn) ?? null

  /* 站位数字只从后端产物来：有已生成报告就取，没生成就不出数（不拿演示值顶）。 */
  useEffect(() => {
    let alive = true
    setStanding(null)
    setHtmlErr('')
    if (!school?.url) { setHtmlBusy(false); return }
    setHtmlBusy(true)
    void (async () => {
      try {
        const res = await fetch(school.url as string, { credentials: 'same-origin' })
        if (!res.ok) throw new Error(String(res.status))
        const html = await res.text()
        if (!alive) return
        setStanding(parseStanding(html))
      } catch {
        if (alive) setHtmlErr('报告正文没读到——可重新生成，或稍后刷新重试')
      } finally {
        if (alive) setHtmlBusy(false)
      }
    })()
    return () => { alive = false }
  }, [school?.url, school?.cn])

  const toggleQueue = (name: string) => {
    setQueue((qq) => qq.includes(name) ? qq.filter((x) => x !== name) : [...qq, name])
  }

  const genCompare = async () => {
    if (queue.length < 2 || cmpBusy) return
    setCmpBusy(true)
    const w = window.open('about:blank', '_blank')
    if (w) {
      w.opener = null
      writeDoc(w, loadingDoc(`${queue.length} 所学校 · 对比报告`))
    }
    try {
      const r = await generateCompareReport(queue)
      const abs1 = new URL(r.url, window.location.origin).href
      if (w && !w.closed) w.location.href = abs1
      else window.open(abs1, '_blank', 'noopener')
    } catch (e) {
      if (w && !w.closed) writeDoc(w, errDoc(e instanceof HttpError ? e.message : '生成没跑成，稍后再试'))
      window.alert(e instanceof HttpError ? e.message : '对比报告没跑成，稍后再试')
    } finally {
      setCmpBusy(false)
    }
  }

  const gen = async (name: string) => {
    if (genBusy === name) return
    setGenErr('')
    setGenBusy(name)
    /* 报告页在点击手势内先开（预开空白页，到手后再回填地址）——await 之后开窗会被弹窗策略拦。 */
    const w = window.open('about:blank', '_blank')
    if (w) {
      w.opener = null
      writeDoc(w, loadingDoc(name))
    }
    try {
      const r = await generateMonitorReport(name)
      const abs1 = new URL(r.url, window.location.origin).href
      if (w && !w.closed) w.location.href = abs1
      else window.open(abs1, '_blank', 'noopener')
      if (!aliveRef.current) return
      setData((d) => d && ({
        ...d,
        schools: d.schools.map((s) => s.cn === name ? { ...s, generated: true, url: r.url } : s),
      }))
    } catch (e) {
      const msg = e instanceof HttpError ? e.message : '生成没跑成，稍后再试'
      if (w && !w.closed) writeDoc(w, errDoc(msg))
      if (aliveRef.current) setGenErr(msg)
    } finally {
      if (aliveRef.current) setGenBusy('')
    }
  }

  const list = (data?.schools ?? []).filter((s) =>
    (tier === 'all' || (tier === '985' ? s.is985 : !s.is985)) &&
    (!q.trim() || s.cn.includes(q.trim()) || s.en.toLowerCase().includes(q.trim().toLowerCase())))
  const n985 = data?.schools.filter((s) => s.is985).length ?? 0
  const nAll = data?.schools.length ?? 0

  const rows = standing?.rows ?? []
  const entered = new Set(rows.map((r) => r.cn))
  const absent = DISCIPLINES.filter((d) => !entered.has(d.cn))
    .sort((a, b) => a.en.localeCompare(b.en))

  return (
    <div className="whs-root">
      <div className="whs-spread">
        <aside className="whs-l">
          <i className="whs-seal" aria-hidden="true">衡</i>
          <header className="whs-bm">
            <b>文衡</b>
            <span>云南大学图书馆<br />学科信息参考</span>
          </header>
          <nav className="whs-nav" aria-label="工作区">
            <a href="/app/">出报告</a>
            <a href="/app/?view=analysis">分析台</a>
            <a href="/app/schools/" aria-current="page">高校 ESI 报告</a>
            <a href="/app/dialog/">问文衡</a>
            <span className="whs-m" aria-hidden="true">管 理</span>
            <a href="/app/?view=archive">运行档案</a>
            <a className="whs-q" href="/app/shelf/">陈列馆 ↗</a>
          </nav>
          <footer className="whs-idb">
            <div className="whs-rule" aria-hidden="true" />
            <p>{nAll ? `院校 ${nAll} 所` : '院校清单'}</p>
          </footer>
        </aside>

        <main className="whs-r">
          <div className="whs-sheet">

            <div className="whs-bar">
              <p className="whs-eyebrow">高校 ESI 报告</p>
              <label className="whs-pick">
                <span className="whs-k">期次</span>
                <span className="whs-sel">
                  <select aria-label="期次" value={data?.period ?? ''} disabled={!data}>
                    {data?.period
                      ? <option value={data.period}>{data.period}</option>
                      : <option value="">—</option>}
                  </select>
                </span>
              </label>
            </div>

            <header className="whs-head">
              <button type="button" className="whs-name" aria-haspopup="dialog"
                      onClick={() => setPickOpen(true)}>
                {cn || '选校'}
                <i aria-hidden="true">⌄</i>
              </button>
              <div className="whs-figs">
                <div className="whs-fig">
                  <span>全球排名</span>
                  <b>{standing?.totals?.rank || '—'}
                    {standing?.totals?.rankAll ? <i>/ {standing.totals.rankAll}</i> : null}</b>
                </div>
                <div className="whs-fig"><span>国内排名</span><b>—</b></div>
                <div className="whs-fig"><span>论文</span><b>{standing?.totals?.papers || '—'}</b></div>
                <div className="whs-fig"><span>被引</span><b>{standing?.totals?.cites || '—'}</b></div>
                <div className="whs-fig"><span>篇均</span><b>{standing?.totals?.per || '—'}</b></div>
              </div>
            </header>

            <div className="whs-rule" aria-hidden="true" />

            <div className="whs-tools">
              {school?.url && (
                <a className="whs-tool" href={school.url} target="_blank" rel="noopener">打开报告 ↗</a>
              )}
              {school && (
                school.generated
                  ? <button type="button" className="whs-tool"
                            disabled={!!genBusy}
                            onClick={() => { void gen(school.cn) }}>
                      {genBusy === school.cn ? '重新生成中…' : '重新生成'}
                    </button>
                  : <button type="button" className="whs-tool go"
                              disabled={!!genBusy}
                              onClick={() => { void gen(school.cn) }}>
                      {genBusy === school.cn ? '生成中…' : '生成报告'}
                    </button>
              )}
              <button type="button" className="whs-tool" onClick={() => setPickOpen(true)}>院校清单</button>
            </div>

            {genErr && <p className="whs-empty" role="alert">{genErr}</p>}

            {loadErr && (
              <p className="whs-empty">
                <b>清单没读到</b>{loadErr}
                <button type="button" className="whs-tool" onClick={() => { void load() }}>重新读取</button>
              </p>
            )}
            {!loadErr && !data && <p className="whs-empty">院校清单读取中……</p>}

            {data && !htmlBusy && !standing && !htmlErr && school && (
              <p className="whs-empty">
                <b>{school.known ? '这一期还没有报告' : '本期 ESI 未收录该校'}</b>
              </p>
            )}
            {htmlErr && <p className="whs-empty" role="alert">{htmlErr}</p>}

            {standing && (
              <section className="whs-tbl" role="table" aria-label="22 学科站位">
                <div className="whs-hd" role="row">
                  <span role="columnheader">学科</span>
                  <span role="columnheader">全球排名</span>
                  <span role="columnheader">国内排名</span>
                  <span role="columnheader">论文</span>
                  <span role="columnheader">被引</span>
                  <span role="columnheader">篇均</span>
                </div>
                {rows.map((r) => (
                  <div key={r.cn} className="whs-rw" role="row">
                    <span className="whs-nm" role="cell">{r.cn}<i aria-hidden="true" /></span>
                    <span className="whs-rn" role="cell">{r.rank}</span>
                    <span className="whs-rn" role="cell">{r.rankCn}</span>
                    <span className="whs-nv" role="cell">{r.papers}</span>
                    <span className="whs-nv" role="cell">{r.cites}</span>
                    <span className="whs-nv" role="cell">{r.per}</span>
                  </div>
                ))}
                {rows.length > 0 && absent.length > 0 && <div className="whs-seg" role="presentation" />}
                {absent.map((d) => (
                  <div key={d.cn} className="whs-rw off" role="row">
                    <span className="whs-nm" role="cell">{d.cn}</span>
                    <span role="cell">—</span>
                    <span role="cell">—</span>
                    <span role="cell">—</span>
                    <span role="cell">—</span>
                    <span role="cell">—</span>
                  </div>
                ))}
              </section>
            )}

            {queue.length > 0 && (
              <div className="whs-queue" role="region" aria-label="对比队列">
                <span className="whs-qn">对 比</span>
                <span className="whs-chips">
                  {queue.map((name) => (
                    <button key={name} type="button" className="whs-chip" title="移出队列"
                            onClick={() => toggleQueue(name)}>{name}<i aria-hidden="true">×</i></button>
                  ))}
                </span>
                <button type="button" className="whs-qgo"
                        disabled={cmpBusy || queue.length < 2}
                        onClick={() => { void genCompare() }}>
                  {cmpBusy ? '生成中…' : '一键生成对比'}
                </button>
              </div>
            )}

            <footer className="whs-foot">文衡 · Clarivate ESI {data?.period ?? '—'}</footer>
          </div>
        </main>
      </div>

      {pickOpen && (
        <div className="whs-mask" onClick={() => setPickOpen(false)}>
          <aside className="whs-drawer" role="dialog" aria-modal="true" aria-label="院校清单"
                 onClick={(e) => e.stopPropagation()}>
            <header className="whs-dh">
              <h2>院校清单</h2>
              <span>{nAll} 所</span>
              <button type="button" className="whs-dx" aria-label="关闭"
                      onClick={() => setPickOpen(false)}>✕</button>
            </header>
            <div className="whs-dbar">
              <div className="whs-tabs" role="tablist" aria-label="院校分组">
                {(['all', '985', '211'] as const).map((t) => (
                  <button key={t} type="button" role="tab" className="whs-tab"
                          aria-pressed={tier === t} onClick={() => setTier(t)}>
                    {t === 'all' ? '全部' : t === '985' ? '985' : '211'}
                    <em>{t === 'all' ? nAll : t === '985' ? n985 : nAll - n985}</em>
                  </button>
                ))}
              </div>
              <div className="whs-search">
                <input type="search" value={q} placeholder="搜校名" aria-label="搜校名"
                       onChange={(e) => setQ(e.target.value)} />
              </div>
            </div>
            <ul className="whs-list">
              {list.map((s: MonitorSchool) => (
                <li key={s.cn} className={`whs-li${s.cn === cn ? ' now' : ''}`}>
                  <button type="button" onClick={() => { setCn(s.cn); setPickOpen(false) }}>
                    <span className="whs-ln">{s.cn}</span>
                    <span className={`whs-ls ${s.generated ? 'ok' : s.known ? '' : 'warn'}`}>
                      {s.generated ? '已生成' : s.known ? '未生成' : '未入册'}
                    </span>
                  </button>
                  <button type="button" className="whs-plus" aria-pressed={queue.includes(s.cn)}
                          aria-label={`${queue.includes(s.cn) ? '移出' : '加入'}对比队列：${s.cn}`}
                          title={queue.includes(s.cn) ? '移出对比队列' : '加入对比队列'}
                          onClick={() => toggleQueue(s.cn)}>＋</button>
                </li>
              ))}
              {data && list.length === 0 && <li className="whs-empty">没有匹配的学校</li>}
            </ul>
            <div className="whs-dfoot">
              <button type="button" className="whs-dbtn go"
                      disabled={cmpBusy || queue.length < 2}
                      onClick={() => { void genCompare() }}>
                {cmpBusy ? '生成中…' : `生成对比（${queue.length}）`}
              </button>
              <button type="button" className="whs-dbtn" onClick={() => setQueue([])}
                      disabled={!queue.length}>清空对比</button>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
