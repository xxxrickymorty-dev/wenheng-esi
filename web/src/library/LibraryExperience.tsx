import type { ShelfBookPreview } from './types'
import { LibraryScene } from './scene/LibraryScene'
import './experience.css'

export type ExperienceStage = 'exterior' | 'entering' | 'room' | 'returning'
type BuildingView = 'front' | 'aerial'

type LibraryExperienceProps = {
  books: ShelfBookPreview[]
  stage: ExperienceStage
  motion: boolean
  soundEnabled: boolean
  view: BuildingView
  returnIssue: number | null
  onMotionChange: (motion: boolean) => void
  onSoundToggle: () => void
  onViewChange: (view: BuildingView) => void
  onEnterRoom: () => void
  onBackHome: () => void
  onPickBook: (index: number) => void
  onTakeStart: (index: number) => void
  onReturnComplete: () => void
  onOpenPreview: (index: number, trigger: HTMLButtonElement) => void
}

export default function LibraryExperience({
  books,
  stage,
  motion,
  soundEnabled,
  view,
  returnIssue,
  onMotionChange,
  onSoundToggle,
  onViewChange,
  onEnterRoom,
  onBackHome,
  onPickBook,
  onTakeStart,
  onReturnComplete,
  onOpenPreview,
}: LibraryExperienceProps) {
  const where = stage === 'exterior' || stage === 'entering'
    ? '建筑入口'
    : stage === 'returning'
      ? '馆藏归架中'
      : '学科情报阅览室'

  return <section className={`site stage-${stage}`}>
    <div className="scene-wrap" aria-hidden="true">
      <LibraryScene
        books={books}
        mode={stage === 'exterior' || stage === 'entering' ? 'exterior' : 'room'}
        entering={stage === 'entering'}
        motion={motion}
        onPick={onPickBook}
        onTakeStart={onTakeStart}
        returnIssue={stage === 'returning' ? returnIssue : null}
        onReturnComplete={onReturnComplete}
        view={view}
      />
    </div>

    <div className="grain" aria-hidden="true" />

    <header className="topbar">
      <button className="brand" type="button" onClick={onBackHome} aria-label="返回云南大学图书馆首页">
        <span className="brand-mark">雲</span>
        <span><strong>云南大学图书馆</strong><small>YUNNAN UNIVERSITY LIBRARY</small></span>
      </button>
      <div className="topbar-right">
        <span>{where}</span>
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

    {(stage === 'exterior' || stage === 'entering') && <>
      <section className="entry-content" aria-labelledby="library-entry-title">
        <p className="eyebrow">呈贡校区 <span>/</span> 建筑外观模型</p>
        <h1 id="library-entry-title">云南大学<br /><em>图书馆</em></h1>
        <p className="entry-lead">环绕查看建筑，再进入学科情报阅览室。</p>
        <button className="primary-button" type="button" onClick={onEnterRoom} disabled={stage === 'entering'}>
          {stage === 'entering' ? '正在进入阅览室' : '进入阅览室'}<span aria-hidden="true">↗</span>
        </button>
        <div className="entry-number">
          <strong>阅</strong>
          <span>报告全内容<br />指标 · 大表 · 预测 · 全文</span>
        </div>
      </section>

      <div className="model-controls" role="group" aria-label="建筑视角">
        <button type="button" className={view === 'front' ? 'active' : ''} aria-pressed={view === 'front'} onClick={() => onViewChange('front')}>正面</button>
        <button type="button" className={view === 'aerial' ? 'active' : ''} aria-pressed={view === 'aerial'} onClick={() => onViewChange('aerial')}>鸟瞰</button>
        <span>拖动旋转 · 滚轮缩放</span>
      </div>
    </>}

    {(stage === 'room' || stage === 'returning') && <div className="room-ui">
      <header className="room-heading">
        <p className="eyebrow">COLLECTION / A—01</p>
        <h1 tabIndex={-1}>学科情报特藏</h1>
        <p>将鼠标移到中央展台的书册上，点击即可取阅。</p>
      </header>

      {stage === 'room' && books.length > 0 && <details className="room-catalog-list">
        <summary>馆藏目录</summary>
        <ul>{books.map((book, index) => <li key={`${book.cover[2]}-${index}`}><button type="button" onClick={(event) => onOpenPreview(index, event.currentTarget)}>打开 {book.cover[2]} 封面预览</button></li>)}</ul>
      </details>}

      <div className="room-bottom">
        <div className="shelf-label">
          <span>馆藏位置</span>
          <strong>学科信息参考 · 历期报告</strong>
          <em>中央八角展台 · 开放封面、目录与名词解释</em>
        </div>
      </div>
      {stage === 'room' && <button className="back-outside" type="button" onClick={onBackHome}>← 返回建筑首页</button>}
    </div>}

    {stage === 'returning' && <div className="returning-note" aria-live="polite"><span>RETURNING TO COLLECTION</span><strong>馆藏归架中</strong></div>}

    <footer className="site-footer">
      <span>会泽百家　至公天下</span>
      <span>YNU · DIGITAL COLLECTION <b>—</b> 馆藏全内容</span>
    </footer>
  </section>
}
