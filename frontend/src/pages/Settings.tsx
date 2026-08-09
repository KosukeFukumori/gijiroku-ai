// 設定ページ: Gemini モデル名・プロンプトの編集
import { useCallback, useEffect, useState } from 'react'
import { fetchSettings, updateSettings } from '../api'
import type { Settings as SettingsType } from '../types'
import { Toast } from '../components/Toast'

interface ToastState {
  message: string
  type: 'info' | 'error' | 'success'
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsType | null>(null)
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  const applyToForm = (data: SettingsType) => {
    setSettings(data)
    setModel(data.gemini_model_is_default ? '' : data.gemini_model)
    setPrompt(data.prompt_is_default ? '' : data.prompt)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      applyToForm(await fetchSettings())
    } catch (e) {
      const msg = e instanceof Error ? e.message : '設定の取得に失敗しました'
      setToast({ message: msg, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await updateSettings({ gemini_model: model.trim(), prompt: prompt.trim() })
      applyToForm(updated)
      setToast({ message: '設定を保存しました', type: 'success' })
    } catch (e) {
      const msg = e instanceof Error ? e.message : '設定の保存に失敗しました'
      setToast({ message: msg, type: 'error' })
    } finally {
      setSaving(false)
    }
  }

  const handleResetModel = () => setModel('')
  const handleResetPrompt = () => setPrompt('')

  if (loading || !settings) {
    return (
      <div className="loading-state">
        <span className="loading-spinner" aria-hidden />
        読み込み中...
      </div>
    )
  }

  return (
    <div>
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      <div className="page-header">
        <h1 className="page-title">設定</h1>
      </div>

      <div className="settings-form">
        <div className="settings-field">
          <label htmlFor="settings-model">Gemini モデル名</label>
          <p className="settings-field-hint">
            未入力の場合は環境変数のデフォルト値（{settings.gemini_model_default}）を使用します
          </p>
          <input
            id="settings-model"
            className="settings-input"
            type="text"
            value={model}
            placeholder={settings.gemini_model_default}
            onChange={(e) => setModel(e.target.value)}
          />
          <div className="settings-field-actions">
            <button className="btn btn-ghost btn-sm" onClick={handleResetModel}>
              デフォルトに戻す
            </button>
          </div>
        </div>

        <div className="settings-field">
          <label htmlFor="settings-prompt">プロンプト</label>
          <p className="settings-field-hint">
            未入力の場合は既定のプロンプトを使用します
          </p>
          <textarea
            id="settings-prompt"
            className="settings-textarea"
            value={prompt}
            placeholder={settings.prompt_default}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="settings-field-actions">
            <button className="btn btn-ghost btn-sm" onClick={handleResetPrompt}>
              デフォルトに戻す
            </button>
          </div>
        </div>

        <div className="settings-actions">
          <button
            className="btn btn-primary"
            disabled={saving}
            onClick={() => { void handleSave() }}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
