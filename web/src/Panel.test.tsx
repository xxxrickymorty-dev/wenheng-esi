import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.stubGlobal('window', { location: { search: '?schools=云南大学' } })
vi.mock('./lib/panelData', () => ({
  getPanelData: () => new Promise(() => {}),
}))
vi.mock('./charts/ChartFigure', () => ({
  ChartFigure: () => null,
}))

import { Panel } from './Panel'

describe('Panel 冒烟', () => {
  it('能渲染', () => {
    const html = renderToStaticMarkup(<Panel />)
    expect(html).toContain('他校简报')
  })
})
