/* 高校 ESI 报告（监测版）——独立整页入口，照 rick 审过的静态稿
   `mockups/全站静态稿-20261102/高校ESI报告-静态稿（20261102）.html`
   （跨页书式：左会泽品牌面 / 右纸面站位表）。与主壳（App.tsx 顶栏式）不共用壳：
   本页自含壳，导航链回主壳各视图。样式全在本目录 schools.css（`whs-` 前缀）。 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/noto-serif-sc'
import '../index.css'
import './schools.css'
import SchoolsPage from './SchoolsPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SchoolsPage />
  </StrictMode>,
)
