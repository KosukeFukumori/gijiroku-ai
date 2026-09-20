// 共通レイアウト: 画面上部に浮かぶピル型ナビ + コンテンツ領域
import { Link, Outlet, useLocation } from 'react-router-dom'
import { ThemeToggle } from './ThemeToggle'

export function Layout() {
  const { pathname } = useLocation()

  return (
    <div className="layout">
      <header className="nav">
        <Link to="/" className="nav-brand bevel">
          <span className="nav-seal" aria-hidden>
            議
          </span>
          <span className="nav-brand-name">議事録AI</span>
        </Link>

        <nav className="nav-menu bevel">
          <Link to="/" className={`nav-link${pathname === '/' ? ' nav-link--active' : ''}`}>
            録音
          </Link>
          <span className="nav-divider" aria-hidden />
          <Link
            to="/settings"
            className={`nav-link${pathname === '/settings' ? ' nav-link--active' : ''}`}
          >
            設定
          </Link>
        </nav>

        <div className="nav-tools">
          <ThemeToggle />
        </div>
      </header>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
