import type { AgentEvent } from '../api/types'

/** 执行 `eventSummary` 对应的界面或业务逻辑。 */
function eventSummary(event: AgentEvent): string {
  const parts: string[] = []
  if (event.step != null) parts.push(`step=${event.step}`)
  if (event.tool_call) parts.push(`tool=${event.tool_call.name}`)
  if (event.tool_result) {
    parts.push(`success=${event.tool_result.success ? 'true' : 'false'}`)
  }
  if (event.approval_decision) parts.push(`decision=${event.approval_decision}`)
  if (event.usage) {
    parts.push(`tokens=${event.usage.total_tokens}`)
  }
  return parts.length > 0 ? ` · ${parts.join(' ')}` : ''
}

/** 格式化 `time` 对应的数据或流程。 */
function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleTimeString()
}

/** 渲染 `TraceTimeline` React 组件。 */
export default function TraceTimeline({
  events,
}: {
  events: AgentEvent[]
}): React.JSX.Element {
  if (events.length === 0) {
    return <div className="empty">该 Run 暂无 Trace 事件。</div>
  }
  return (
    <div>
      {events.map((event) => (
        <div
          key={event.event_id}
          style={{
            display: 'flex',
            gap: 10,
            padding: '4px 0',
            fontSize: 12.5,
            alignItems: 'baseline',
          }}
        >
          <span className="text-muted" style={{ width: 76, flexShrink: 0 }}>
            {formatTime(event.event_time)}
          </span>
          <span className="text-muted" style={{ width: 40, flexShrink: 0 }}>
            #{event.sequence}
          </span>
          <span>
            {event.type}
            {eventSummary(event)}
          </span>
        </div>
      ))}
    </div>
  )
}
