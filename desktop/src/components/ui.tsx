/** Design Foundation — 可复用基础组件（thin，样式全部走 CSS class）。 */

import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactElement,
  ReactNode,
  TextareaHTMLAttributes,
} from 'react'
import { Icon } from './Icon'
import type { IconName } from './Icon'

/* ---------- Button ---------- */

export type ButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
}

/** 执行 `Button` 对应的界面或业务逻辑。 */
export function Button({
  variant = 'default',
  size = 'md',
  className = '',
  ...rest
}: ButtonProps): ReactElement {
  const cls = [
    'btn',
    variant !== 'default' ? `btn-${variant}` : '',
    size === 'sm' ? 'btn-sm' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return <button className={cls} {...rest} />
}

/* ---------- IconButton ---------- */

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName
  label: string
}

/** 执行 `IconButton` 对应的界面或业务逻辑。 */
export function IconButton({
  icon,
  label,
  className = '',
  ...rest
}: IconButtonProps): ReactElement {
  return (
    <button
      type="button"
      className={`icon-btn ${className}`.trim()}
      title={label}
      aria-label={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  )
}

/* ---------- Input / Textarea ---------- */

/** 执行 `Input` 对应的界面或业务逻辑。 */
export function Input({
  className = '',
  ...rest
}: InputHTMLAttributes<HTMLInputElement>): ReactElement {
  return <input className={`input ${className}`.trim()} {...rest} />
}

/** 执行 `Textarea` 对应的界面或业务逻辑。 */
export function Textarea({
  className = '',
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>): ReactElement {
  return <textarea className={`textarea ${className}`.trim()} {...rest} />
}

/* ---------- Badge ---------- */

export type BadgeTone = 'default' | 'success' | 'warning' | 'danger' | 'accent'

/** 执行 `Badge` 对应的界面或业务逻辑。 */
export function Badge({
  tone = 'default',
  className = '',
  children,
}: {
  tone?: BadgeTone
  className?: string
  children: ReactNode
}): ReactElement {
  return (
    <span className={`badge badge--${tone} ${className}`.trim()}>{children}</span>
  )
}

/* ---------- StatusDot ---------- */

export type StatusTone =
  | 'ready'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'offline'

/** 执行 `StatusDot` 对应的界面或业务逻辑。 */
export function StatusDot({
  tone,
  className = '',
}: {
  tone: StatusTone
  className?: string
}): ReactElement {
  return (
    <span
      className={`status-dot status-dot--${tone} ${className}`.trim()}
      data-status={tone}
      aria-hidden="true"
    />
  )
}

/* ---------- Card ---------- */

/** 渲染 `Card` React 组件。 */
export function Card({
  subtle = false,
  className = '',
  children,
}: {
  subtle?: boolean
  className?: string
  children: ReactNode
}): ReactElement {
  return (
    <section
      className={`card ${subtle ? 'card--subtle' : ''} ${className}`.trim()}
    >
      {children}
    </section>
  )
}

/* ---------- EmptyState ---------- */

/** 渲染 `EmptyState` React 组件。 */
export function EmptyState({
  title,
  hint,
}: {
  title: string
  hint?: string
}): ReactElement {
  return (
    <div className="empty-state">
      <p className="empty-state__title">{title}</p>
      {hint ? <p className="empty-state__hint">{hint}</p> : null}
    </div>
  )
}

/* ---------- Spinner ---------- */

/** 执行 `Spinner` 对应的界面或业务逻辑。 */
export function Spinner({
  size = 16,
  className = '',
}: {
  size?: number
  className?: string
}): ReactElement {
  return (
    <span
      className={`spinner ${className}`.trim()}
      style={{ width: size, height: size }}
      role="status"
      aria-label="加载中"
    />
  )
}

/* ---------- SectionHeader ---------- */

/** 执行 `SectionHeader` 对应的界面或业务逻辑。 */
export function SectionHeader({
  title,
  hint,
  actions,
}: {
  title: string
  hint?: string
  actions?: ReactNode
}): ReactElement {
  return (
    <div className="section-header">
      <span className="section-header__title">{title}</span>
      {hint ? <span className="section-header__hint">{hint}</span> : null}
      {actions ? <span className="section-header__actions">{actions}</span> : null}
    </div>
  )
}
