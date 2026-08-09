// 確認モーダル（ネイティブ confirm() の置き換え）
import { useCallback, useEffect, useRef, useState } from 'react'

interface ConfirmOptions {
  message: string
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  // true の場合、確定ボタンを危険操作用の見た目にする
  danger?: boolean
}

interface ConfirmState extends ConfirmOptions {
  resolve: (ok: boolean) => void
}

interface ConfirmModalProps extends ConfirmOptions {
  onConfirm: () => void
  onCancel: () => void
}

/** 確認モーダル本体。オーバーレイ・Esc・Enter・背景クリックでの操作に対応 */
function ConfirmModal({
  message,
  title = '確認',
  confirmLabel = 'OK',
  cancelLabel = 'キャンセル',
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancel()
      } else if (e.key === 'Enter') {
        e.preventDefault()
        onConfirm()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onConfirm, onCancel])

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="modal-title">{title}</h2>
        <p className="modal-message">{message}</p>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * ネイティブ confirm() を置き換える確認モーダル用フック。
 * 返り値の confirm() は Promise<boolean> を返すので、
 *   if (!(await confirm({ message: '...' }))) return
 * のように使える。あわせて返る modal を JSX として描画すること。
 */
export function useConfirm(): {
  confirm: (options: ConfirmOptions) => Promise<boolean>
  modal: React.ReactNode
} {
  const [state, setState] = useState<ConfirmState | null>(null)

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setState({ ...options, resolve })
    })
  }, [])

  const close = useCallback((ok: boolean) => {
    setState((prev) => {
      prev?.resolve(ok)
      return null
    })
  }, [])

  const modal = state ? (
    <ConfirmModal
      {...state}
      onConfirm={() => close(true)}
      onCancel={() => close(false)}
    />
  ) : null

  return { confirm, modal }
}
