/* 高校 ESI 报告 · 监测版（入口整页）。
   版面照已审静态稿 `mockups/全站静态稿-20261102/高校ESI报告-静态稿（20261102）.html`；
   2026-11-04 票 3 版式对齐工作区：侧栏零覆盖（共用件 SideRail 原样，与工作区/
   问文衡逐项一致），右页 padding/内容栅格/金线节奏/期次下拉/表格形制对齐
   .app-main 与分析台（.an-*）的版式语言；「院校 N 所」从侧栏挪回
   「院校清单」入口。内容与功能（院校选择、重新生成、院校清单、报告打开、
   轮询兜底）一件未动。
   左页会泽品牌面＋右页报头（眉标 / 校名 / 期次）→ 总站位 → 22 行学科表；
   已入 1% 与未入之间一道 1px 金线，未在榜格子写 `—`。
   能力一件不少：院校清单（选校抽屉）、多校对比（队列）、生成报告（既有 POST 口）。
   数字零口径：总站位与学科行全部解析自后端已生成的站位报告（`/monitor/report/…`），
   前端只搬运显示值，不换算、不补数、不猜期次；后端没有的指标写 `—`。 */

import { useEffect, useRef, useState } from 'react'
import {
  type MonitorSchool, type MonitorSchools,
  generateCompareReport, generateMonitorReport, getMonitorSchools,
} from '../api-monitor'
import { HttpError, getMe, type Me } from '../api'
import { SideRail, useSideRail } from '../SideRail'
import { useSettingsCenter } from '../dialog/ModelPanel'

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

/* 预开页的加载反馈：点击手势内开窗后立刻写入「在跑」，生成完由本页回填报告地址；
   失败则在原页显示原因。离开这个加载页前，用户不是在盯空白。

   2026-11-02 改：原来的五步动画是**假的**——每 600ms 前进一格，第 5 步用 `%` 绕回第 1 步，
   于是进度条从 100% 弹回 20%，看着像「退回去了」。生成接口是同步的（POST 一直挂到算完），
   没有分步进度可读，所以这里改成不确定进度条（来回扫）＋真实已用秒数：
   说清在干什么、已经等了多久，不假装知道干到哪一步。 */
/* 预开页取色器：预开页是 document.write 进新窗口的独立文档，够不着本页样式表、
   读不到 schools.css 的 --whs-* 变量——开窗时从活页 .whs-root 把令牌值读出来，
   拼进预开页自己的 <style>。色值单一来源仍是 schools.css 顶部 --whs-* 段
   （2026-11-03 批三 J，39 分册）。本函数只被本页的生成动作调用，.whs-root 必在 DOM。 */
function docPalette(): (name: string) => string {
  const el = document.querySelector('.whs-root')
  const css = el ? getComputedStyle(el) : null
  return (name) => (css ? css.getPropertyValue(name).trim() : '')
}

function loadingDoc(label: string, pollUrl?: string): string {
  const steps = RUN_STEPS.join(' → ')
  const v = docPalette()
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">` +
    `<title>正在生成 · 文衡监测版</title><style>` +
    `body{margin:0;background:${v('--whs-paper')};color:${v('--whs-doc-ink')};font-family:system-ui,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}` +
    `.box{width:min(440px,86vw);background:${v('--whs-card')};border:1px solid ${v('--whs-doc-line')};border-radius:${v('--whs-r-l')};box-shadow:0 1px 4px rgba(21,34,43,.08);padding:26px 30px}` +
    `.brand{font-family:serif;letter-spacing:.14em;font-size:13px;color:${v('--whs-deep')}}` +
    `h1{font-size:17px;margin:10px 0 4px;font-weight:600}` +
    `.sub{font-size:13.5px;color:${v('--whs-doc-sub')};margin:0 0 14px}` +
    `.bar{position:relative;height:3px;background:${v('--whs-doc-track')};overflow:hidden}` +
    `.fl{position:absolute;top:0;left:0;height:100%;width:38%;background:${v('--whs-doc-flow')};animation:sweep 1.4s cubic-bezier(.45,.05,.55,.95) infinite}` +
    `@keyframes sweep{0%{left:-38%}100%{left:100%}}` +
    `.steps{font-size:12px;color:${v('--whs-doc-sub')};letter-spacing:.04em;margin:12px 0 0}` +
    `.el{font-size:12px;color:${v('--whs-doc-sub')};margin:8px 0 0;font-variant-numeric:tabular-nums}` +
    `.el b{color:${v('--whs-doc-flow')};font-weight:600}` +
    `.hint{font-size:12px;color:${v('--whs-muted')};margin-top:12px;line-height:1.75}` +
    `.rec{display:none;margin-top:14px;gap:8px}` +
    `.rec.on{display:flex}` +
    `.rec a{font-size:12.5px;color:${v('--whs-doc-ink')};background:${v('--whs-doc-flow')};` +
    `color:#fff;padding:7px 14px;border-radius:6px;text-decoration:none;font-weight:600}` +
    `.rec button{font-size:12.5px;color:${v('--whs-doc-sub')};background:none;` +
    `border:1px solid ${v('--whs-doc-line')};padding:7px 14px;border-radius:6px;cursor:pointer}` +
    `@media (prefers-reduced-motion:reduce){.fl{animation:none;width:100%;opacity:.35}}` +
    `</style></head><body><div class="box">` +
    `<div class="brand">文衡 · 高校 ESI 报告</div>` +
    `<h1>正在生成：${label}</h1>` +
    `<p class="sub">完成后本页自动跳转为报告。</p>` +
    `<div class="bar"><div class="fl"></div></div>` +
    `<p class="steps">工序：${steps}</p>` +
    `<p class="el">已用 <b id="el">0</b> 秒</p>` +
    `<p class="hint" id="hint">五道工序一次跑完，中途没有分步进度；跑完会自动跳转。若超过两三分钟没有动静，回上一页看状态或重新生成。</p>` +
    `<div class="rec" id="rec">` +
    (pollUrl ? `<a id="go" href="${pollUrl}">打开报告</a>` : ``) +
    `<button type="button" onclick="history.length>1?history.back():close()">回上一页</button>` +
    `</div>` +
    `<script>` +
    `var t=0,el=document.getElementById('el');setInterval(function(){t+=1;el.textContent=t},1000);` +
    // 看门狗（2026-11-04）：生成口的请求如果断在半路，本页会永远转圈——
    // 单校与对比报告的落盘地址都可探测（对比件走 /api/monitor/compare-status），
    // 每 10s 探测一次，落盘即跳；探测口不可用时 60s 亮出兜底按钮，不让用户干等。
    (pollUrl
      ? `var poll=function(){fetch('${pollUrl}',{method:'GET',credentials:'same-origin',cache:'no-store'})` +
        `.then(function(r){if(!r.ok)throw 0;` +
        `return r.json().then(function(j){return (j&&j.url)?j.url:'${pollUrl}'},` +
        `function(){return '${pollUrl}'})})` +
        `.then(function(u){if(u)location.replace(u)}).catch(function(){})};` +
        `setInterval(poll,10000);setTimeout(poll,1500);`
      : ``) +
    `setTimeout(function(){document.getElementById('rec').className='rec on'},60000);` +
    `</script>` +
    `</div></body></html>`
}

function errDoc(msg: string): string {
  const v = docPalette()
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>生成失败 · 文衡监测版</title>` +
    `<style>body{margin:0;background:${v('--whs-paper')};color:${v('--whs-doc-ink')};font-family:system-ui,"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}.box{width:min(420px,86vw);background:${v('--whs-card')};border:1px solid ${v('--whs-doc-line')};padding:26px 30px}.t{font-size:15px;font-weight:600;color:${v('--whs-bad')};margin:0 0 8px}.m{font-size:12.5px;color:${v('--whs-doc-ink-2')};line-height:1.8;margin:0}</style></head>` +
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

  /* 左页侧栏换装 SideRail（2026-11-03 票 1）：宽度/收起偏好与工作区、问文衡同键同件。
     me/roleKnown 用 api.ts 现成 getMe（内部吞错）：拿不到就是未登录占位，不冒充馆员。 */
  const rail = useSideRail()
  const [me, setMe] = useState<Me | null>(null)
  const [roleKnown, setRoleKnown] = useState(false)
  useEffect(() => {
    void getMe().then((m) => {
      if (!aliveRef.current) return
      setMe(m)
      setRoleKnown(true)
    })
  }, [])
  /* 设置中心（2026-11-04 票 1 收进共享接线 useSettingsCenter）：
     齿轮 / Ctrl+, 带出；清单自拉，本页不消费模型清单。
     非 admin / 未登录照 hint 只读。 */
  const settings = useSettingsCenter(me)

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
    /* 对比件地址也确定性（后端按校名集合哈希落盘），状态口探测落盘即跳（20261104）：
       与单校同一套轮询兜底——生成口请求断在半路时本页不再永远转圈。 */
    const pollUrl = data?.period && queue.length >= 2
      ? `/api/monitor/compare-status?schools=${encodeURIComponent(queue.join(','))}` +
        `&period=${encodeURIComponent(data.period)}`
      : undefined
    const w = window.open('about:blank', '_blank')
    if (w) {
      w.opener = null
      writeDoc(w, loadingDoc(`${queue.length} 所学校 · 对比报告`, pollUrl))
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
    /* 报告页在点击手势内先开（预开空白页，到手后再回填地址）——await 之后开窗会被弹窗策略拦。
       单校报告地址可预知（/monitor/report/<校名>/<期次>.html），预开页拿它做轮询兜底。 */
    const pollUrl = data?.period
      ? `/monitor/report/${encodeURIComponent(name)}/${data.period}.html`
      : undefined
    const w = window.open('about:blank', '_blank')
    if (w) {
      w.opener = null
      writeDoc(w, loadingDoc(name, pollUrl))
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
    <div className="whs-root" {...rail.rootProps}>
      <div className="whs-spread">
        {/* 左页侧栏（2026-11-03 票 1 换装；2026-11-04 票 3 起与工作区/问文衡完全同一套）：
            共用件 SideRail——品牌/导航/管理组/折叠/口径ⓘ/身份行/齿轮/收展钮零覆盖；
            「院校 N 所」是页内信息，收进右页「院校清单」入口（不再塞进侧栏中段）；
            不传 period——期次控件在右页报头（2026-11-03 登记的分工，保留）。 */}
        <SideRail rail={rail} active="schools" me={me} roleKnown={roleKnown}
                  onSettings={settings.show} />

        <main className="whs-r">
          <div className="whs-sheet">

            <div className="whs-bar">
              <p className="whs-eyebrow">高校 ESI 报告</p>
              {/* 期次下拉与工作区同形（描边小盒，悬停提示；只有一期，禁用即可读） */}
              <label className="whs-pick">
                <span className="whs-sel">
                  <select aria-label="期次" title="期次" value={data?.period ?? ''} disabled={!data}>
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
              {/* 清单规模长在入口上（2026-11-04 票 3：原侧栏「院校 N 所」挪回页内） */}
              <button type="button" className="whs-tool" onClick={() => setPickOpen(true)}>
                {nAll ? `院校清单 · ${nAll}` : '院校清单'}
              </button>
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

      {/* 设置中心（useSettingsCenter 接线）：清单自拉，onChanged 空实现
          ——本页不消费模型清单。非 admin / 未登录照 hint 只读。 */}
      {settings.node}
    </div>
  )
}
