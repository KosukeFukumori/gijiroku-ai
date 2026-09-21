// 読み進み表示（rareui.com の Scroll Progress を参考にした進捗ピル）
// 画面右下に現在地を出し、クリックで見出し一覧に展開して飛べる。
import { useCallback, useEffect, useRef, useState } from 'react'

export interface ScrollSection {
  /** 飛び先の要素 id */
  id: string
  /** 一覧に出す見出し */
  label: string
  /** 見出しの階層（1 が最上位）。字下げに使う */
  depth?: number
}

interface Props {
  sections: ScrollSection[]
}

// ナビと固定ツールバーの下に見出しが隠れないよう空ける量
const SCROLL_OFFSET = 150

export function ScrollProgress({ sections }: Props) {
  const [open, setOpen] = useState(false)
  const [ratio, setRatio] = useState(0)
  const [currentId, setCurrentId] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)

  // スクロール位置から進捗と現在の見出しを求める
  const update = useCallback(() => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight
    setRatio(scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 0)

    let current: string | null = null
    for (const section of sections) {
      const el = document.getElementById(section.id)
      if (!el) continue
      if (el.getBoundingClientRect().top <= SCROLL_OFFSET + 1) current = section.id
    }
    setCurrentId(current ?? sections[0]?.id ?? null)
  }, [sections])

  useEffect(() => {
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [update])

  // 展開中は画面外クリックと Esc で閉じる
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // 文字起こしは数万pxに及ぶため、スムーズスクロールは使わず一息に飛ばす
  // （Chrome は距離が大きいとスムーズスクロールが動かないことがあるうえ、
  //   動いたとしても待たされるだけで実用的でない）
  const jumpTo = (id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    window.scrollTo({
      top: el.getBoundingClientRect().top + window.scrollY - SCROLL_OFFSET,
      behavior: 'auto',
    })
    setOpen(false)
  }

  // 飛び先が1つしかないなら出す意味がない
  if (sections.length < 2) return null

  const current = sections.find((s) => s.id === currentId) ?? sections[0]
  const percent = Math.round(ratio * 100)

  return (
    <div className={`scroll-progress${open ? ' scroll-progress--open' : ''}`} ref={rootRef}>
      {open && (
        <div className="scroll-progress-menu" role="menu">
          {sections.map((section) => (
            <button
              key={section.id}
              role="menuitem"
              className={`scroll-progress-item${
                section.id === current.id ? ' scroll-progress-item--current' : ''
              }`}
              style={{ paddingLeft: 14 + ((section.depth ?? 1) - 1) * 14 }}
              onClick={() => jumpTo(section.id)}
            >
              {section.label}
            </button>
          ))}
        </div>
      )}

      <button
        className="scroll-progress-pill"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`読み進み ${percent}パーセント。現在地 ${current.label}。見出し一覧を開く`}
      >
        <span
          className="scroll-progress-ring"
          style={{ ['--ratio' as string]: `${percent}%` }}
          aria-hidden
        >
          <span className="scroll-progress-ring-hole" />
        </span>
        <span className="scroll-progress-label">{current.label}</span>
      </button>
    </div>
  )
}
