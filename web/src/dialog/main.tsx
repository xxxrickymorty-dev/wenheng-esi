import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/noto-serif-sc'
import '../index.css'
import './dialog.css'
import DialogPage from './DialogPage'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('缺少页面根节点')
}

createRoot(rootElement).render(
  <StrictMode>
    <DialogPage />
  </StrictMode>,
)
