// エントリーポイント
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { App } from './App'

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('#root 要素が見つかりません')

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
