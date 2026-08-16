// 録音詳細ページ: 「文字起こし」「議事録」タブを切り替える
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { audioUrl, deleteRecording, fetchRecording, retryRecording, subscribeEvents } from '../api'
import type { RecordingDetail as RecordingDetailType, Segment } from '../types'
import { ProcessBadge } from '../components/Badge'
import { Toast } from '../components/Toast'
import { useConfirm } from '../components/ConfirmModal'

type Tab = 'transcript' | 'minutes'

/** 秒数を mm:ss 形式に変換（duration_sec は float なので整数へ丸める） */
function formatDuration(sec: number | null): string {
  if (sec == null) return '-'
  const total = Math.round(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 秒数を [mm:ss] 形式に変換 */
function formatTimestamp(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
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

export function RecordingDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const recordingId = id ?? ''

  const [detail, setDetail] = useState<RecordingDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [tab, setTab] = useState<Tab>('minutes')
  const { confirm, modal } = useConfirm()
  // SSE から受信した要約の累積テキスト（要約中のみ表示）
  const [summaryProgress, setSummaryProgress] = useState<string | null>(null)
  // SSE から受信した処理段階のテキスト（ローカル文字起こし・話者識別など、
  // segment_added / summary_progress が出るまでの間の状況表示用）
  const [stageText, setStageText] = useState<string | null>(null)
  // 現在再生中のセグメント id
  const [activeSegId, setActiveSegId] = useState<number | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchRecording(recordingId)
      setDetail(data)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '詳細の取得に失敗しました'
      setToast({ message: msg, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [recordingId])

  useEffect(() => {
    void load()
  }, [load])

  // SSE でリアルタイム更新（この録音の recording_id のイベントのみ処理）
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    if (!recordingId) return
    const unsubscribe = subscribeEvents((event) => {
      if (event.type === 'recording_updated' && event.recording_id === recordingId) {
        setDetail((prev) =>
          prev ? { ...prev, process_status: event.process_status } : prev,
        )
        void loadRef.current()
        if (event.process_status === 'processing') {
          setStageText(null)
        } else {
          setSummaryProgress(null)
          setStageText(null)
        }
      } else if (event.type === 'stage_progress' && event.recording_id === recordingId) {
        setStageText(event.text)
      } else if (event.type === 'segment_added' && event.recording_id === recordingId) {
        setDetail((prev) => {
          if (!prev) return prev
          const seg = event.segment as Segment
          if (prev.segments.some((s) => s.id === seg.id)) return prev
          return { ...prev, segments: [...prev.segments, seg] }
        })
      } else if (event.type === 'summary_progress' && event.recording_id === recordingId) {
        setSummaryProgress(event.text)
        setStageText(null)
      }
    })
    return unsubscribe
  }, [recordingId])

  // timeupdate イベントで現在再生中のセグメントをハイライト
  const handleTimeUpdate = () => {
    if (!audioRef.current || !detail) return
    const currentTime = audioRef.current.currentTime
    const seg = detail.segments.find(
      (s) => currentTime >= s.start_sec && currentTime < s.end_sec,
    )
    setActiveSegId(seg?.id ?? null)
  }

  // セグメントクリック: 該当位置にシーク＆再生
  const handleSegmentClick = (startSec: number) => {
    if (!audioRef.current) return
    audioRef.current.currentTime = startSec
    void audioRef.current.play()
  }

  const handleDelete = async () => {
    if (!(await confirm({
      title: '録音を削除',
      message: 'この録音を完全に削除しますか？音源ファイル・文字起こし・議事録はすべて削除され、元に戻せません。',
      confirmLabel: '削除',
      danger: true,
    }))) return
    try {
      await deleteRecording(recordingId)
      setToast({ message: '削除しました', type: 'success' })
      setTimeout(() => navigate('/'), 800)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '削除に失敗しました'
      setToast({ message: msg, type: 'error' })
    }
  }

  const handleRetry = async () => {
    try {
      await retryRecording(recordingId)
      setToast({ message: '再試行を開始しました', type: 'success' })
      void load()
    } catch (e) {
      const msg = e instanceof Error ? e.message : '再試行の開始に失敗しました'
      setToast({ message: msg, type: 'error' })
    }
  }

  if (loading && !detail) {
    return (
      <div className="loading-state">
        <span className="loading-spinner" aria-hidden />
        読み込み中...
      </div>
    )
  }
  if (!detail) return <p className="empty-text">録音が見つかりません</p>

  const isProcessing = detail.process_status === 'processing'
  const showSummary = isProcessing || detail.summary !== null

  return (
    <div>
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}
      {modal}

      <div className="page-header">
        <div className="page-header-left">
          <button className="btn btn-ghost btn-sm detail-back" onClick={() => navigate('/')}>
            ← 一覧に戻る
          </button>
          <h1 className="page-title">{detail.title ?? detail.original_filename}</h1>
          <div className="detail-meta">
            <span>
              <span className="detail-meta-label">日時</span>
              {formatDatetime(detail.meeting_datetime)}
            </span>
            <span>
              <span className="detail-meta-label">時間</span>
              {formatDuration(detail.duration_sec)}
            </span>
            <ProcessBadge status={detail.process_status} />
          </div>
        </div>
        <div className="detail-actions">
          {detail.process_status === 'error' && (
            <button className="btn btn-secondary" onClick={() => { void handleRetry() }}>
              再試行
            </button>
          )}
          <button className="btn btn-danger" onClick={() => { void handleDelete() }}>
            削除
          </button>
        </div>
      </div>

      {detail.process_status === 'error' && detail.error_message && (
        <div className="error-box">
          <strong>エラー:</strong> {detail.error_message}
        </div>
      )}

      {isProcessing && stageText && (
        <p className="stage-progress-text">
          <span className="loading-spinner" aria-hidden />
          {stageText}
        </p>
      )}

      <audio
        ref={audioRef}
        controls
        src={audioUrl(recordingId)}
        onTimeUpdate={handleTimeUpdate}
        className="audio-player"
      />

      <div className="tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'minutes'}
          className={`tab-btn${tab === 'minutes' ? ' tab-btn--active' : ''}`}
          onClick={() => setTab('minutes')}
        >
          議事録
        </button>
        <button
          role="tab"
          aria-selected={tab === 'transcript'}
          className={`tab-btn${tab === 'transcript' ? ' tab-btn--active' : ''}`}
          onClick={() => setTab('transcript')}
        >
          文字起こし
        </button>
      </div>

      {tab === 'minutes' && (
        <div>
          {showSummary && (
            <div className="section">
              <h2 className="section-title">議事録</h2>
              {isProcessing ? (
                <p className="summary-text">
                  {summaryProgress ?? ''}
                  <span className="streaming-cursor" aria-hidden>▍</span>
                </p>
              ) : (
                <div className="summary-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.summary}</ReactMarkdown>
                </div>
              )}
            </div>
          )}

          {detail.decisions.length > 0 && (
            <div className="section">
              <h2 className="section-title">決定事項</h2>
              <ul className="decisions-list">
                {detail.decisions.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {detail.action_items.length > 0 && (
            <div className="section">
              <h2 className="section-title">アクションアイテム</h2>
              <ul className="action-items">
                {detail.action_items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {!showSummary && !isProcessing && (
            <p className="empty-text">議事録はまだ生成されていません</p>
          )}
        </div>
      )}

      {tab === 'transcript' && (
        <div className="section">
          <div className="segments">
            {detail.segments.map((seg) => (
              <div
                key={seg.id}
                className={`segment${activeSegId === seg.id ? ' segment-active' : ''}`}
                onClick={() => handleSegmentClick(seg.start_sec)}
                title="クリックでこの位置から再生"
              >
                <span className="segment-time">{formatTimestamp(seg.start_sec)}</span>
                {seg.speaker && <span className="segment-speaker">{seg.speaker}</span>}
                <span className="segment-text">{seg.text}</span>
              </div>
            ))}
            {isProcessing && (
              <div className="transcribing-indicator">
                <span className="transcribing-dot" aria-hidden />
                文字起こし・議事録生成中...
              </div>
            )}
            {detail.segments.length === 0 && !isProcessing && (
              <p className="empty-text">文字起こしはまだ生成されていません</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
