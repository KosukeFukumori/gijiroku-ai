// 録音ファイルのドラッグ&ドロップ / ファイル選択アップロード領域（複数ファイル対応）
import { useRef, useState } from 'react'

interface Props {
  onUpload: (files: File[]) => Promise<void>
  disabled?: boolean
}

export function UploadDropzone({ onUpload, disabled = false }: Props) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const handleFiles = async (files: File[]) => {
    if (files.length === 0) return
    setUploading(true)
    try {
      await onUpload(files)
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    if (disabled || uploading) return
    void handleFiles(Array.from(e.dataTransfer.files))
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    void handleFiles(files)
  }

  const busy = disabled || uploading

  return (
    <div
      className={`dropzone${dragging ? ' dropzone--dragging' : ''}${busy ? ' dropzone--busy' : ''}`}
      onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => { if (!busy) inputRef.current?.click() }}
      role="button"
      tabIndex={0}
      aria-disabled={busy}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".m4a,.mp3,.wav,.aac,.amr,.ogg,.flac"
        multiple
        className="dropzone-input"
        onChange={handleInputChange}
        disabled={busy}
      />
      <div className="dropzone-icon" aria-hidden>{uploading ? '⏳' : '🎙️'}</div>
      <p className="dropzone-title">
        {uploading ? 'アップロード中...' : '録音ファイルをドラッグ&ドロップ'}
      </p>
      {!uploading && (
        <p className="dropzone-desc">
          またはクリックしてファイルを選択（複数選択可、m4a, mp3, wav, aac, amr, ogg, flac）
        </p>
      )}
    </div>
  )
}
