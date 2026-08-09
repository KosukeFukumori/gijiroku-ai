// トースト通知コンポーネント
import { useEffect } from 'react'

interface Props {
  message: string
  type?: 'info' | 'error' | 'success'
  onClose: () => void
  durationMs?: number
}

/** 一定時間後に自動で消えるトースト通知 */
export function Toast({ message, type = 'info', onClose, durationMs = 4000 }: Props) {
  useEffect(() => {
    const timer = setTimeout(onClose, durationMs)
    return () => clearTimeout(timer)
  }, [onClose, durationMs])

  return (
    <div className={`toast toast-${type}`} onClick={onClose}>
      {message}
    </div>
  )
}
