import { useEffect, useRef, useState } from 'react'

import type { AgentMode } from '../api/types'
import CommandPalette, { type ComposerCommand } from './CommandPalette'
import { Icon } from './Icon'

export type { ComposerCommand }

export interface ComposerProps {
  disabled: boolean
  sending?: boolean
  /** 当前 run 正在执行中：发送按钮转为暂停按钮。 */
  running?: boolean
  onStop?: () => void
  mode?: AgentMode
  onModeChange?: (mode: AgentMode) => void
  /** 为当前任务生成待审核 Skill。 */
  onGenerateSkill?: () => void
  canGenerateSkill?: boolean
  generatingSkill?: boolean
  onSend: (content: string) => Promise<void>
  value?: string
  onValueChange?: (value: string) => void
  /** 轻量 Command palette 项（⌘K）。 */
  commands?: ComposerCommand[]
}

/** 执行 `Composer` 对应的界面或业务逻辑。 */
export default function Composer({
  disabled,
  sending = false,
  running = false,
  onStop,
  mode = 'normal',
  onModeChange,
  onGenerateSkill,
  canGenerateSkill = false,
  generatingSkill = false,
  onSend,
  value,
  onValueChange,
  commands,
}: ComposerProps): React.JSX.Element {
  const [internalValue, setInternalValue] = useState('')
  const [commandOpen, setCommandOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const draft = value ?? internalValue
  const busy = disabled || sending || generatingSkill
  const canSend = draft.trim() !== '' && !busy

  useEffect(() => {
    /** 响应 `onKey` 对应的事件。 */
    const onKey = (event: KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /** 设置 `draft` 对应的数据或流程。 */
  const setDraft = (next: string): void => {
    if (value === undefined) setInternalValue(next)
    onValueChange?.(next)
  }

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = '0px'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
  }, [draft])

  /** 执行 `submit` 对应的界面或业务逻辑。 */
  const submit = async (): Promise<void> => {
    const content = draft.trim()
    if (!content || busy) return
    setDraft('')
    try {
      await onSend(content)
    } catch {
      // 发送失败时恢复草稿，避免用户输入丢失。
      setDraft(content)
    }
  }

  return (
    <div className="composer-dock">
      <div className={`composer ${busy ? 'composer--busy' : ''}`}>
        <textarea
          ref={textareaRef}
          className="composer__input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void submit()
            }
          }}
          placeholder="告诉 Pluto 你想完成什么…"
          rows={1}
          disabled={busy}
          aria-label="消息输入框"
        />
        <div className="composer__footer">
          <div className="mode-switch" aria-label="执行模式">
            {(['normal', 'plan'] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={`mode-switch__item ${mode === item ? 'active' : ''}`}
                onClick={() => onModeChange?.(item)}
                aria-pressed={mode === item}
                title={
                  item === 'plan'
                    ? '规划模式会先调查并生成计划，等待你确认后再执行。'
                    : '普通模式会直接执行你的请求。'
                }
                disabled={busy || !onModeChange}
              >
                {item === 'normal' ? '普通' : '规划'}
              </button>
            ))}
            <button
              type="button"
              className="mode-switch__item"
              onClick={() => onGenerateSkill?.()}
              disabled={busy || running || !canGenerateSkill || !onGenerateSkill}
              aria-label="为当前任务生成 Skill"
              title={
                canGenerateSkill
                  ? '从当前任务已有的执行证据中提炼 Skill，确认后保存。'
                  : '当前会话还没有包含执行记录的任务。'
              }
            >
              {generatingSkill ? '生成中…' : '生成 Skill'}
            </button>
          </div>
          {running ? (
            <button
              type="button"
              className="composer__send composer__stop"
              onClick={() => onStop?.()}
              aria-label="暂停"
              title="暂停"
            >
              <Icon name="pause" size={16} />
            </button>
          ) : (
            <button
              type="button"
              className="composer__send"
              onClick={() => void submit()}
              disabled={!canSend}
              aria-label={sending ? '正在发送' : '发送'}
              title="发送"
            >
              {sending ? <span className="spinner spinner--light" /> : <Icon name="send" size={16} />}
            </button>
          )}
        </div>
      </div>
      <CommandPalette
        open={Boolean(commands?.length) && commandOpen}
        commands={commands ?? []}
        onClose={() => setCommandOpen(false)}
      />
    </div>
  )
}
