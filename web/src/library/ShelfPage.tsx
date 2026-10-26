/* 陈列馆壳：五态加载（loading / login / forbidden / unavailable / invalid-data）+ 取数，
   成功态整页交给 LibraryHome。
   2026-10-25 起按 mockups/陈列馆-完整（静态稿 20261025）.html 落地：
   翻书器与音效模块随旧版退役，不再接线（旧件文件保留不删）。 */

import { useEffect, useState } from 'react'
import { loadShelfPreviews } from './data'
import LibraryHome from './LibraryHome'
import type { ShelfLoadResult } from './types'

type PageState =
  | { kind: 'loading' }
  | ShelfLoadResult

export default function ShelfPage() {
  const [state, setState] = useState<PageState>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    void loadShelfPreviews(controller.signal).then((result) => {
      if (controller.signal.aborted) return
      setState(result)
    }).catch(() => {
      if (!controller.signal.aborted) setState({ kind: 'unavailable' })
    })

    return () => controller.abort()
  }, [attempt])

  function retry() {
    setAttempt((current) => current + 1)
  }

  if (state.kind === 'loading') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <p className="library-status" role="status" aria-live="polite">
            <b>文衡 · 陈列馆</b>
            <span>正在确认身份并调取馆藏……</span>
          </p>
        </div>
      </main>
    )
  }

  if (state.kind === 'login') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>请先登录</h1>
            <p>登录后才能阅览馆藏全内容。</p>
            <a className="library-action" href="/login">前往登录</a>
          </section>
        </div>
      </main>
    )
  }

  if (state.kind === 'forbidden') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>暂时无法打开馆藏</h1>
            <p>当前账号无法查看这份馆藏内容。</p>
            <button className="library-action" type="button" onClick={retry}>再试一次</button>
          </section>
        </div>
      </main>
    )
  }

  if (state.kind === 'unavailable' || state.kind === 'invalid-data') {
    return (
      <main className="library-page">
        <div className="library-shell">
          <section className="library-message" role="alert">
            <h1>馆藏暂不可用</h1>
            <p>{state.kind === 'invalid-data'
              ? '目前读到的内容不符合可阅览范围，因此没有显示。'
              : '现在无法确认身份或读取馆藏内容，请稍后重试。'}</p>
            <button className="library-action" type="button" onClick={retry}>再试一次</button>
          </section>
        </div>
      </main>
    )
  }

  return <LibraryHome books={state.books} stats={state.stats} />
}
