/** Windows Computer Runtime 的紧凑产品状态。 */

import { leaseLabel } from '../api/computer'
import type { ComputerStatus } from '../api/computer'
import { StatusDot } from './ui'

/** 渲染 `ComputerStatusView` React 组件。 */
export default function ComputerStatusView({
  status,
  loading = false,
}: {
  status: ComputerStatus | null
  loading?: boolean
}): React.JSX.Element {
  if (loading && !status) return <div className="loading-inline"><span className="spinner" /> 正在检查电脑操作状态…</div>
  if (!status) return <div className="empty-inline empty-inline--error">无法获取电脑操作状态</div>

  const reason = status.reason === 'runtime_init_failed'
    ? 'Windows 运行时初始化失败'
    : status.reason

  return (
    <div className="computer-status-view">
      <div className="computer-status-view__runtime">
        <StatusDot tone={status.available ? 'ready' : 'failed'} />
        <div>
          <strong>{status.available ? '可用' : '不可用'}</strong>
          <span>
            {status.available
              ? `电脑操作运行时 · ${status.runtime ?? status.platform}`
              : reason ?? '运行时不可用'}
          </span>
        </div>
        <small>{leaseLabel(status.lease)}</small>
      </div>
      <div className="runtime-capabilities">
        <span>Win32 输入控制</span>
        <span>GDI 屏幕捕获</span>
      </div>
    </div>
  )
}
