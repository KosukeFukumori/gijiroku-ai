// PDF 出力メニュー: 「議事録」「文字起こし」の 2 種類をダウンロードさせる
import { useEffect, useRef, useState } from 'react'
import { IconChevronDown, IconDocument } from './Icon'

export interface ExportMenuItem {
  label: string
  /** ダウンロード先（サーバが Content-Disposition でファイル名を付ける） */
  href: string
  /** まだ生成されていない場合は選べないようにする */
  disabled?: boolean
  /** 選べない理由（ツールチップ表示用） */
  disabledReason?: string
}

interface Props {
  items: ExportMenuItem[]
}

export function ExportMenu({ items }: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  // メニュー外のクリックと Esc で閉じる
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="export-menu" ref={rootRef}>
      <button
        className="btn btn-secondary"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <IconDocument size={15} />
        PDF出力
        <IconChevronDown size={13} />
      </button>

      {open && (
        <div className="export-menu-panel" role="menu">
          {items.map((item) => (
            <a
              key={item.label}
              role="menuitem"
              className={`export-menu-item${item.disabled ? ' export-menu-item--disabled' : ''}`}
              href={item.disabled ? undefined : item.href}
              // 同一オリジンなので download 属性で画面遷移せずに保存できる
              // （ファイル名はサーバの Content-Disposition が優先される）
              download
              title={item.disabled ? item.disabledReason : undefined}
              aria-disabled={item.disabled}
              onClick={() => { if (!item.disabled) setOpen(false) }}
            >
              {item.label}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
