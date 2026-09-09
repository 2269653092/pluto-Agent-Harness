/** ComputerStatusView 渲染测试（renderToStaticMarkup，无 DOM）。 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { ComputerStatus } from '../api/computer'
import ComputerStatusView from './ComputerStatusView'

const status: ComputerStatus = {
  enabled: true,
  available: true,
  platform: 'windows',
  runtime: 'windows',
  reason: null,
  lease: { busy: false, owner_run_id: '', acquired_at: null, process_id: 1 },
}

describe('ComputerStatusView', () => {
  it('available 渲染 Windows 状态与能力', () => {
    const html = renderToStaticMarkup(<ComputerStatusView status={status} />)
    expect(html).toContain('可用')
    expect(html).toContain('Win32 输入控制')
    expect(html).toContain('GDI 屏幕捕获')
    expect(html).toContain('空闲')
  })

  it('unavailable 渲染初始化失败原因', () => {
    const html = renderToStaticMarkup(
      <ComputerStatusView
        status={{
          ...status,
          available: false,
          reason: 'runtime_init_failed',
          lease: null,
        }}
      />,
    )
    expect(html).toContain('不可用')
    expect(html).toContain('Windows 运行时初始化失败')
  })
})
