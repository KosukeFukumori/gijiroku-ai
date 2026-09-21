// 処理段階のトラック表示（rareui.com の Step player を参考にした段階インジケータ）
// 完了した段階は点、進行中の段階は棒に伸びて満ちていく。所要時間は事前に
// 分からないため、満ち方は繰り返しのアニメーションで表す。
import type { ProcessStep } from '../types'

interface Props {
  /** 現在の段階。まだ段階が届いていなければ null */
  active: ProcessStep | null
  /** 段階の説明文（バックエンドから届くテキスト） */
  text: string | null
}

const STEPS: { key: ProcessStep; label: string }[] = [
  { key: 'transcribe', label: '文字起こし' },
  { key: 'diarize', label: '話者識別' },
  { key: 'minutes', label: '議事録の生成' },
]

export function StageTrack({ active, text }: Props) {
  const activeIndex = active === null ? -1 : STEPS.findIndex((s) => s.key === active)

  return (
    <div className="stage-track">
      <div
        className="stage-rail"
        role="progressbar"
        aria-valuemin={1}
        aria-valuemax={STEPS.length}
        aria-valuenow={activeIndex + 1}
        aria-valuetext={active === null ? '準備中' : STEPS[activeIndex].label}
      >
        {STEPS.map((step, i) => {
          const state = i < activeIndex ? 'done' : i === activeIndex ? 'active' : 'todo'
          return (
            <span key={step.key} className={`stage-step stage-step--${state}`} title={step.label}>
              {state === 'active' && <span className="stage-step-fill" />}
            </span>
          )
        })}
      </div>
      <p className="stage-track-text">
        {text ?? '処理の準備をしています'}
        {activeIndex >= 0 && (
          <span className="stage-track-count">
            {activeIndex + 1} / {STEPS.length}
          </span>
        )}
      </p>
    </div>
  )
}
