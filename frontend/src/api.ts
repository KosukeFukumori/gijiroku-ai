// ============================================================
// バックエンド API クライアント
// ============================================================

import type { AppEvent, RecordingDetail, RecordingList } from './types'

const BASE = '/api'

/** 共通エラー処理付き fetch */
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API エラー [${res.status}]: ${text}`)
  }
  return res.json() as Promise<T>
}

// ============================================================
// 録音一覧・詳細
// ============================================================

export interface RecordingListParams {
  q?: string
  /** 処理状況（複数指定は OR 条件。API へはカンマ区切りで渡す） */
  statuses?: string[]
  page?: number
  page_size?: number
}

export function fetchRecordings(params: RecordingListParams = {}): Promise<RecordingList> {
  const q = new URLSearchParams()
  if (params.q) q.set('q', params.q)
  if (params.statuses && params.statuses.length > 0) {
    q.set('status', params.statuses.join(','))
  }
  if (params.page != null) q.set('page', String(params.page))
  if (params.page_size != null) q.set('page_size', String(params.page_size))
  const qs = q.toString()
  return apiFetch<RecordingList>(`/recordings${qs ? `?${qs}` : ''}`)
}

export function fetchRecording(id: string): Promise<RecordingDetail> {
  return apiFetch<RecordingDetail>(`/recordings/${id}`)
}

/** 音源 URL（<audio src> に指定） */
export function audioUrl(id: string): string {
  return `${BASE}/recordings/${id}/audio`
}

// ============================================================
// 録音アップロード・操作
// ============================================================

export async function uploadRecording(file: File, title: string): Promise<RecordingDetail> {
  const form = new FormData()
  form.append('file', file)
  if (title.trim()) form.append('title', title.trim())
  const res = await fetch(`${BASE}/recordings`, { method: 'POST', body: form })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`アップロードに失敗しました [${res.status}]: ${text}`)
  }
  return res.json() as Promise<RecordingDetail>
}

export function deleteRecording(id: string): Promise<unknown> {
  return apiFetch(`/recordings/${id}`, { method: 'DELETE' })
}

export function retryRecording(id: string): Promise<unknown> {
  return apiFetch(`/recordings/${id}/retry`, { method: 'POST' })
}

// ============================================================
// リアルタイムイベント（SSE: GET /api/events）
// ============================================================

/**
 * GET /api/events を EventSource で購読し、イベントを callback に渡す。
 * 解除関数を返す（EventSource を close する）。
 */
export function subscribeEvents(onEvent: (e: AppEvent) => void): () => void {
  const es = new EventSource(`${BASE}/events`)

  es.onmessage = (e: MessageEvent) => {
    try {
      const event = JSON.parse(e.data as string) as AppEvent
      onEvent(event)
    } catch {
      // パースエラーは無視
    }
  }

  // エラー時は自動再接続に任せる
  es.onerror = () => { /* 自動再接続 */ }

  return () => es.close()
}
