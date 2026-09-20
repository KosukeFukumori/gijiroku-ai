// ダーク / ライトの切り替えトグル（選択は localStorage に保存）
import { useEffect, useState } from 'react'
import { IconMoon, IconSun } from './Icon'

type Theme = 'dark' | 'light'

const STORAGE_KEY = 'gijiroku-theme'

/** 保存済みテーマを読む。未保存なら OS の設定に従う */
function initialTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const next = theme === 'dark' ? 'light' : 'dark'

  return (
    <button
      className="icon-btn"
      onClick={() => setTheme(next)}
      aria-label={next === 'dark' ? 'ダークに切り替え' : 'ライトに切り替え'}
      title={next === 'dark' ? 'ダークに切り替え' : 'ライトに切り替え'}
    >
      {theme === 'dark' ? <IconMoon size={16} /> : <IconSun size={16} />}
    </button>
  )
}
