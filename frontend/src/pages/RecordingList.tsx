// 録音一覧ページ（アップロード領域を兼ねる）
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchRecordings, subscribeEvents, uploadRecording } from '../api'
import type { RecordingListItem } from '../types'
import { ProcessBadge } from '../components/Badge'
import { Toast } from '../components/Toast'
import { UploadDropzone } from '../components/UploadDropzone'
import { IconArrowUpRight, IconMic } from '../components/Icon'

/** 秒数を mm:ss 形式に変換（duration_sec は float なので整数へ丸める） */
function formatDuration(sec: number | null): string {
  if (sec == null) return '-'
  const total = Math.round(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 要約の冒頭を一行プレビュー用に整える（Markdown 記法を落とす） */
function toPlainPreview(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/\*\*|__|`|~~/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 会議日時を読みやすい文字列に変換 */
function formatDatetime(dt: string): string {
  return new Date(dt).toLocaleString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface ToastState {
  message: string
  type: 'info' | 'error' | 'success'
}

export function RecordingList() {
  const navigate = useNavigate()

  const [items, setItems] = useState<RecordingListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchRecordings({ page_size: 100 })
      setItems(res.items)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '一覧の取得に失敗しました'
      setToast({ message: msg, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // SSE でリアルタイム更新（連続イベントをまとめて再読込）
  const loadRef = useRef(load)
  loadRef.current = load
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const unsubscribe = subscribeEvents((event) => {
      if (event.type === 'recordings_changed' || event.type === 'recording_updated') {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        debounceRef.current = setTimeout(() => { void loadRef.current() }, 400)
      }
    })
    return () => {
      unsubscribe()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const handleUpload = async (files: File[]) => {
    let success = 0
    let lastError = ''
    for (const file of files) {
      try {
        await uploadRecording(file)
        success++
      } catch (e) {
        lastError = e instanceof Error ? e.message : 'アップロードに失敗しました'
      }
    }
    void load()
    const failed = files.length - success
    if (failed === 0) {
      setToast({ message: `${success}件アップロードしました。処理を開始します`, type: 'success' })
    } else if (success === 0) {
      setToast({ message: lastError || 'アップロードに失敗しました', type: 'error' })
    } else {
      setToast({ message: `${success}件成功、${failed}件失敗しました`, type: 'error' })
    }
  }

  return (
    <div>
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">録音</h1>
          <p className="page-lead">
            {items.length > 0 ? `${items.length}件の録音` : '会議の録音を追加すると、文字起こしと議事録を自動で作ります'}
          </p>
        </div>
      </div>

      <UploadDropzone onUpload={handleUpload} />

      {loading && items.length === 0 && (
        <div className="loading-state">
          <span className="loading-spinner" aria-hidden />
          読み込み中...
        </div>
      )}

      <div className="recording-list">
        {items.length === 0 && !loading && (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden><IconMic size={28} /></div>
            <p className="empty-state-title">まだ録音がありません</p>
            <p className="empty-state-desc">上の枠に録音ファイルをドロップすると、処理が始まります</p>
          </div>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            className={`recording-card recording-card--${item.process_status}`}
            onClick={() => navigate(`/recordings/${item.id}`)}
          >
            <div className="recording-card-header">
              <span className="recording-title">{item.title ?? 'タイトルは生成中です'}</span>
              <ProcessBadge status={item.process_status} />
              <IconArrowUpRight size={16} className="recording-card-arrow" />
            </div>
            <div className="recording-card-meta">
              <span>
                <span className="recording-meta-label">日時</span>
                {formatDatetime(item.meeting_datetime)}
              </span>
              <span>
                <span className="recording-meta-label">時間</span>
                {formatDuration(item.duration_sec)}
              </span>
            </div>
            {item.summary_head && (
              <p className="recording-summary-head">{toPlainPreview(item.summary_head)}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
