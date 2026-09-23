import gsap from 'gsap'
import { useEffect, useRef, useState } from 'react'

type Period = {
  period: string
  signed: boolean
  label: string
}

type State =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; periods: Period[] }

function App() {
  const [state, setState] = useState<State>({ status: 'loading' })
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    let cancelled = false

    fetch('/api/periods')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<{ periods?: Period[] }>
      })
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', periods: data.periods ?? [] })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' })
      })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (state.status !== 'ready' || !listRef.current) return
    const items = listRef.current.querySelectorAll('li')
    if (items.length === 0) return

    const tween = gsap.fromTo(
      items,
      { opacity: 0, y: 12 },
      { opacity: 1, y: 0, duration: 0.4, stagger: 0.06, ease: 'power2.out' },
    )

    return () => {
      tween.kill()
    }
  }, [state.status])

  return (
    <main className="min-h-screen bg-neutral-50 text-neutral-900">
      <div className="mx-auto w-full max-w-2xl px-6 py-16">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">文衡 · 工作区</h1>
          <p className="mt-2 text-sm text-neutral-500">
            学科信息服务的工作入口，按期次查看与流转。
          </p>
        </header>

        {/* 陈列馆入口：历期卷宗（G 的体验，作为静态子应用挂在 /app/shelf/） */}
        <a
          href="/app/shelf/"
          className="mt-8 flex items-center justify-between gap-4 rounded-xl border border-neutral-300 bg-white px-5 py-4 no-underline transition hover:border-neutral-900"
        >
          <span>
            <span className="block text-base font-medium">陈列馆 · 历期卷宗</span>
            <span className="mt-0.5 block text-sm text-neutral-500">
              按期翻看已出刊的报告（书架 → 端详 → 开卷）
            </span>
          </span>
          <span aria-hidden="true" className="text-lg text-neutral-400">
            →
          </span>
        </a>

        <section className="mt-10">
          {state.status === 'loading' && (
            <p className="text-sm text-neutral-500">加载中…</p>
          )}

          {state.status === 'error' && (
            <p
              role="status"
              className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
            >
              接口未就绪，暂时无法获取期次列表。
            </p>
          )}

          {state.status === 'ready' && state.periods.length === 0 && (
            <p className="text-sm text-neutral-500">暂无期次。</p>
          )}

          {state.status === 'ready' && state.periods.length > 0 && (
            <ul
              ref={listRef}
              className="divide-y divide-neutral-200 overflow-hidden rounded-xl border border-neutral-200 bg-white"
            >
              {state.periods.map((item) => (
                <li
                  key={item.period}
                  className="flex items-center justify-between gap-4 px-5 py-4"
                >
                  <div className="flex items-baseline gap-3">
                    <span className="text-sm font-medium">{item.label}</span>
                    <span className="font-mono text-xs text-neutral-400">
                      {item.period}
                    </span>
                  </div>
                  <span
                    className={
                      item.signed
                        ? 'rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs text-emerald-700'
                        : 'rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-500'
                    }
                  >
                    {item.signed ? '已签署' : '未签署'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}

export default App
