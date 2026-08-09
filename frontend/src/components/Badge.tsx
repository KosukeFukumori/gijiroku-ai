// ステータスバッジコンポーネント
import type { ProcessStatus } from '../types'

interface ProcessBadgeProps {
  status: ProcessStatus
}

/** 処理ステータスの日本語ラベル（バッジ・フィルタで共用） */
export const PROCESS_STATUS_LABELS: Record<ProcessStatus, string> = {
  pending: '処理待ち',
  processing: '処理中',
  done: '完了',
  error: 'エラー',
}

/** 処理ステータスバッジ（ドット + ラベル のピル型） */
export function ProcessBadge({ status }: ProcessBadgeProps) {
  const isPulsing = status === 'processing'

  return (
    <span className={`badge badge-${status}`}>
      <span className={`badge-dot${isPulsing ? ' badge-dot--pulse' : ''}`} aria-hidden />
      {PROCESS_STATUS_LABELS[status]}
    </span>
  )
}
