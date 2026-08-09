// 共通レイアウト: スティッキーナビ付きのページ外枠
import { Link, Outlet } from 'react-router-dom'

export function Layout() {
  return (
    <div className="layout">
      <header className="nav-header">
        <Link to="/" className="nav-brand">
          <span className="nav-seal" aria-hidden>議</span>
          <span className="nav-brand-name">議事録AI</span>
        </Link>
        <Link to="/settings" className="nav-settings-link" aria-label="設定" title="設定">
          ⚙️
        </Link>
      </header>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
