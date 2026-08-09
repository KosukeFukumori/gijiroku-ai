// ============================================================
// API レスポンスの型定義
// ============================================================

/** 処理ステータス */
export type ProcessStatus = 'pending' | 'processing' | 'done' | 'error'

/** 一覧用の録音アイテム */
export interface RecordingListItem {
  id: string
  title: string | null
  meeting_datetime: string
  duration_sec: number | null
  process_status: ProcessStatus
  summary_head: string | null
}

/** 文字起こしセグメント */
export interface Segment {
  id: number
  start_sec: number
  end_sec: number
  /** 個人名 または「話者A」等の匿名ラベル。未識別は null */
  speaker: string | null
  text: string
}

/** 詳細用の録音アイテム */
export interface RecordingDetail {
  id: string
  original_filename: string
  title: string | null
  meeting_datetime: string
  duration_sec: number | null
  process_status: ProcessStatus
  summary: string | null
  decisions: string[]
  action_items: string[]
  error_message: string | null
  created_at: string
  updated_at: string
  segments: Segment[]
}

/** 一覧 API レスポンス */
export interface RecordingList {
  items: RecordingListItem[]
  total: number
}

/** GET /api/events の SSE イベント型 */
export type AppEvent =
  | { type: 'recordings_changed' }
  | { type: 'recording_updated'; recording_id: string; process_status: ProcessStatus }
  | { type: 'segment_added'; recording_id: string; segment: Segment }
  | { type: 'summary_progress'; recording_id: string; text: string }
