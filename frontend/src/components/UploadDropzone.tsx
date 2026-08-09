// 録音ファイルのドラッグ&ドロップ / ファイル選択アップロード領域
import { useRef, useState } from 'react'

interface Props {
  onUpload: (file: File, title: string) => Promise<void>
  disabled?: boolean
}

export function UploadDropzone({ onUpload, disabled = false }: Props) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const handleFile = async (file: File) => {
    setUploading(true)
    try {
      await onUpload(file, '')
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    if (disabled || uploading) return
    const file = e.dataTransfer.files[0]
    if (file) void handleFile(file)
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) void handleFile(file)
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
        className="dropzone-input"
        onChange={handleInputChange}
        disabled={busy}
      />
      <div className="dropzone-icon" aria-hidden>{uploading ? '⏳' : '🎙️'}</div>
      <p className="dropzone-title">
        {uploading ? 'アップロード中...' : '録音ファイルをドラッグ&ドロップ'}
      </p>
      {!uploading && (
        <p className="dropzone-desc">またはクリックしてファイルを選択（m4a, mp3, wav, aac, amr, ogg, flac）</p>
      )}
    </div>
  )
}
