/* 高校 ESI 报告 · 插件市场（监测版）。
   布局与文案照静态稿（mockups/高校ESI报告-插件市场（静态稿 20261031）.html，rick 已审）：
   左会泽品牌面（金句「换校，不换产线。」）+ 右至公槽位面（985/211 页签 + 搜校名 + 卡片网格）。
   与静态稿的三处落码差异（都是把演示态换成真状态）：
   ① 状态机收成 未生成 / 生成中 / 已生成（静态稿的「建档/初稿待签/已签发」是云大产线语言，
      监测版 v1 没有签单流程，不挂假状态）；
   ② 生成是真实请求（缓存已建时秒回），五步进度条照播、播完即真完成；
   ③ 名单按教育部名录与 ESI 机构写法校准：109 所（矿大/石油/地大分址并一卡；
      北京体育大学/中央音乐学院非 211 不收；西南交通大学已补）。
   数字零口径：清单与状态全来自 /api/monitor/schools，生成走 /api/monitor/report。 */

import { useEffect, useRef, useState } from 'react'
import {
  type MonitorSchool, type MonitorSchools,
  generateCompareReport, generateMonitorReport, getMonitorSchools,
} from '../api-monitor'
import { HttpError } from '../api'

const RUN_STEPS = ['取数', '拼表', '出稿', '核验', '签发']

type CardState = { busy: boolean; step: number; done: boolean; url: string | null; err: string }

export default function SchoolsPage() {
  const [data, setData] = useState<MonitorSchools | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [tier, setTier] = useState<'all' | '985' | '211'>('all')
  const [q, setQ] = useState('')
  const [cards, setCards] = useState<Record<string, CardState>>({})
  const [queue, setQueue] = useState<string[]>([])
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
    } catch (e) {
      if (!aliveRef.current || id !== reqRef.current) return
      setLoadErr(e instanceof HttpError ? e.message : '院校清单没读到——确认服务在运行后重试')
    }
  }
  useEffect(() => { void load() }, [])

  const toggleQueue = (cn: string) => {
    setQueue((qq) => qq.includes(cn) ? qq.filter((x) => x !== cn) : [...qq, cn])
  }

  const genCompare = async () => {
    if (queue.length < 2 || cmpBusy) return
    setCmpBusy(true)
    const w = window.open('about:blank', '_blank')
    if (w) w.opener = null
    try {
      const r = await generateCompareReport(queue)
      if (w && !w.closed) w.location.href = r.url
      else window.open(r.url, '_blank', 'noopener')
    } catch (e) {
      if (w && !w.closed) w.close()
      setQueue((qq) => [...qq])
      window.alert(e instanceof HttpError ? e.message : '对比报告没跑成，稍后再试')
    } finally {
      setCmpBusy(false)
    }
  }

  const gen = async (cn: string) => {
    /* 进度条按静态稿节奏播（5 步）；真实请求并行跑，两边都齐才算完成。
       报告页在点击手势内先开（预开空白页，到手后再回填地址）——await 之后开窗会被弹窗策略拦。 */
    const w = window.open('about:blank', '_blank')
    if (w) w.opener = null
    setCards((c): Record<string, CardState> => ({ ...c, [cn]: { busy: true, step: 0, done: false, url: null, err: '' } }))
    const anim = setInterval(() => {
      setCards((c): Record<string, CardState> => {
        const cur = c[cn]
        if (!cur || !cur.busy) return c
        return { ...c, [cn]: { ...cur, step: Math.min(cur.step + 1, RUN_STEPS.length - 1) } }
      })
    }, 600)
    try {
      const r = await generateMonitorReport(cn)
      await new Promise((res) => setTimeout(res, RUN_STEPS.length * 600 + 350))
      clearInterval(anim)
      if (!aliveRef.current) return
      setCards((c): Record<string, CardState> => ({ ...c, [cn]: { busy: false, step: 0, done: true, url: r.url, err: '' } }))
      setData((d) => d && ({
        ...d,
        schools: d.schools.map((s) => s.cn === cn ? { ...s, generated: true, url: r.url } : s),
      }))
      if (w && !w.closed) {
        w.location.href = r.url
      } else {
        window.open(r.url, '_blank', 'noopener')
      }
    } catch (e) {
      clearInterval(anim)
      if (w && !w.closed) w.close()
      setCards((c): Record<string, CardState> => ({
        ...c, [cn]: {
          busy: false, step: 0, done: false, url: null,
          err: e instanceof HttpError ? e.message : '生成没跑成，稍后再试',
        },
      }))
    }
  }

  const list = (data?.schools ?? []).filter((s) =>
    (tier === 'all' || (tier === '985' ? s.is985 : !s.is985)) &&
    (!q.trim() || s.cn.includes(q.trim()) || s.en.toLowerCase().includes(q.trim().toLowerCase())))
  const groups = tier === 'all'
    ? [{ label: '985 工程', items: list.filter((s) => s.is985) },
       { label: '211 工程', items: list.filter((s) => !s.is985) }]
    : [{ label: tier === '985' ? '985 工程' : '211 工程', items: list }]
  const n985 = data?.schools.filter((s) => s.is985).length ?? 0

  return (
    <div className="msch-spread">
      <aside className="msch-l">
        <div className="msch-bm"><b>文衡</b><span>云南大学图书馆<br />学科信息参考</span></div>
        <nav className="msch-nav" aria-label="工作区">
          <a href="/app/">出报告</a>
          <a href="/app/schools/" aria-current="page">高校 ESI 报告</a>
          <a href="/app/dialog/">问文衡</a>
          <span className="msch-m">管 理</span>
          <a href="/app/?view=archive">运行档案</a>
          <a className="msch-q" href="/app/shelf/">陈列馆 ↗</a>
        </nav>
        <div className="msch-hero">
          <p className="msch-ov">监 测 版 · 全 国 槽 位</p>
          <h1>高校 ESI 报告</h1>
          <p className="msch-vol"><span className="msch-b">{data ? `内置 ${data.schools.length} 所` : '— 所'}</span><span className="msch-c">{n985 ? `985 · 211` : ''}</span></p>
          <div className="msch-rule" />
          <p className="msch-stm">换校，不换产线。</p>
          <p className="msch-sub">数据只要 ESI 每期导出；监测表由系统一期一期替学校攒，从接入当期开始。</p>
          <div className="msch-acts"><a className="msch-btn" href="#msch-grid">从榜单选校 ↓</a></div>
        </div>
      </aside>

      <main className="msch-r">
        <div className="msch-bar" role="toolbar" aria-label="筛选">
          <div className="msch-tabs" role="tablist" aria-label="院校分组">
            {(['all', '985', '211'] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-pressed={tier === t}
                      onClick={() => setTier(t)}>
                {t === 'all' ? '全部' : t.toUpperCase()}<em>
                  {t === 'all' ? (data?.schools.length ?? 0) : t === '985' ? n985 : (data?.schools.length ?? 0) - n985}
                </em>
              </button>
            ))}
          </div>
          <div className="msch-search">
            <input type="search" value={q} placeholder="搜校名" aria-label="搜校名"
                   onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>

        <div className="msch-grid" id="msch-grid" aria-live="polite">
          {loadErr && <p className="msch-empty">{loadErr}<br />
            <button type="button" className="msch-act" onClick={() => { void load() }}>重新读取</button></p>}
          {!loadErr && !data && <p className="msch-empty">院校清单读取中……</p>}
          {data && list.length === 0 && <p className="msch-empty">没有匹配的学校</p>}
          {groups.map((g) => g.items.length > 0 && (
            <div key={g.label} className="msch-gsec">
              <h2 className="msch-gtitle">{g.label}</h2>
              <div className="msch-ggrid">
                {g.items.map((s) => (
                  <Slot key={s.cn} s={s} st={cards[s.cn]} inQueue={queue.includes(s.cn)}
                        onGen={() => { void gen(s.cn) }} onQueue={() => toggleQueue(s.cn)} />
                ))}
              </div>
            </div>
          ))}
        </div>

        {queue.length > 0 && (
          <div className="msch-queue" role="region" aria-label="对比队列">
            <span className="msch-queue-n">对比队列 {queue.length}</span>
            <span className="msch-chips">
              {queue.map((cn) => (
                <button key={cn} type="button" className="msch-chip" title="移出队列"
                        onClick={() => toggleQueue(cn)}>{cn} ×</button>
              ))}
            </span>
            <button type="button" className="msch-act go msch-go"
                    disabled={cmpBusy || queue.length < 2}
                    title={queue.length < 2 ? '至少选 2 所' : '生成对比报告（不限数量）'}
                    onClick={() => { void genCompare() }}>
              {cmpBusy ? '生成中…' : '一键生成对比'}
            </button>
          </div>
        )}
        {data?.built && <p className="msch-foot">数据期 {data.period} · 缓存建于 {data.built} ·
          名单按教育部名录与 ESI 机构写法校准（分址院校在 ESI 为单一实体，并一卡呈现）</p>}
      </main>
    </div>
  )
}

function Slot({ s, st, inQueue, onGen, onQueue }:
              { s: MonitorSchool; st?: CardState; inQueue: boolean;
                onGen: () => void; onQueue: () => void }) {
  const busy = st?.busy
  const qHas = inQueue
  const done = st?.done || s.generated
  return (
    <article className="msch-slot">
      <div className="msch-top">
        <i className="msch-mg" aria-hidden="true">{s.cn.charAt(0)}</i>
        <span className="msch-topr">
          <button type="button"
                  className={`msch-add ${qHas ? 'on' : ''}`}
                  aria-pressed={qHas}
                  title={qHas ? '移出对比队列' : '加入对比队列'}
                  aria-label={`${qHas ? '移出' : '加入'}对比队列：${s.cn}`}
                  onClick={(e) => { e.stopPropagation(); onQueue() }}>＋</button>
          <span className={`msch-bdg ${s.is985 ? 'b985' : 'b211'}`}>{s.is985 ? '985' : '211'}</span>
        </span>
      </div>
      <h3>{s.cn}</h3>
      <div className="msch-foot-row">
        {st?.err
          ? <span className="msch-st msch-st-err">{st.err}</span>
          : <span className={`msch-st ${busy ? 'msch-st-run' : done ? 'msch-st-draft' : 'msch-st-new'}`}>
              {busy ? '生成中' : done ? '已生成' : s.known ? '未生成' : '未入册'}
            </span>}
        {busy
          ? <span className="msch-act" aria-disabled="true" />
          : done && s.url
            ? <a className="msch-act go" href={s.url} target="_blank" rel="noopener">查看</a>
            : <button className="msch-act go" type="button" onClick={onGen}
                      title={s.known ? `生成 ${s.cn} 的站位报告` : '本期 ESI 未收录该校——报告会如实呈现未上榜'}>
                生成
              </button>}
      </div>
      {busy && (
        <div className="msch-prog">
          <div className="msch-tr"><div className="msch-fl"
            style={{ width: `${(Math.min(st?.step ?? 0, RUN_STEPS.length - 1) + 1) / RUN_STEPS.length * 100}%` }} /></div>
          <p className="msch-lb">第 {Math.min((st?.step ?? 0) + 1, RUN_STEPS.length)}/{RUN_STEPS.length} 步 · {RUN_STEPS[Math.min(st?.step ?? 0, RUN_STEPS.length - 1)]}</p>
        </div>
      )}
    </article>
  )
}
