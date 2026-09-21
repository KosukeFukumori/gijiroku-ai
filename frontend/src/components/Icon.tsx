// 画面内で使うラインアイコン群（絵文字の置き換え）
// currentColor で塗るので、親要素の color をそのまま継承する。

interface IconProps {
  size?: number
  className?: string
}

function svgProps({ size = 16, className }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
  }
}

/** 設定（スライダー） */
export function IconSettings(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="8" cy="12" r="2" />
      <circle cx="14" cy="18" r="2" />
    </svg>
  )
}

/** マイク（録音） */
export function IconMic(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  )
}

/** 上向き矢印（アップロード） */
export function IconUpload(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  )
}

/** 左向き矢印（戻る） */
export function IconArrowLeft(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M19 12H5M11 18l-6-6 6-6" />
    </svg>
  )
}

/** 右上向き矢印（カードの遷移マーク） */
export function IconArrowUpRight(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M7 17 17 7M8 7h9v9" />
    </svg>
  )
}

/** 太陽（ライトテーマ） */
export function IconSun(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2v2M12 20v2M4.2 4.2l1.5 1.5M18.3 18.3l1.5 1.5M2 12h2M20 12h2M4.2 19.8l1.5-1.5M18.3 5.7l1.5-1.5" />
    </svg>
  )
}

/** 月（ダークテーマ） */
export function IconMoon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.2 8.2 0 1 0 10.2 10.2Z" />
    </svg>
  )
}

/** 書類（PDF 出力） */
export function IconDocument(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </svg>
  )
}

/** 下向き山形（メニューの開閉） */
export function IconChevronDown(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}
