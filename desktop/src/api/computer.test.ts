/** Computer API 测试：method 名 / params / screenshot URL / lease label。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))

vi.mock('../rpc', () => ({
  rpcClient: { call: callMock },
}))

import {
  buildComputerScreenshotUrl,
  getComputerStatus,
  getLatestComputerObservation,
  leaseLabel,
} from './computer'
import { SERVER_URL } from './config'

describe('computer api', () => {
  beforeEach(() => {
    callMock.mockReset()
  })

  it('computer.status 空 params', async () => {
    callMock.mockResolvedValue({ enabled: true, available: false })
    const status = await getComputerStatus()
    expect(callMock).toHaveBeenCalledWith('computer.status', {})
    expect(status.available).toBe(false)
  })

  it('computer.latest_observation 不带 run_id 用空 params', async () => {
    callMock.mockResolvedValue({ observation: null })
    await getLatestComputerObservation()
    expect(callMock).toHaveBeenCalledWith('computer.latest_observation', {})
  })

  it('computer.latest_observation 带 run_id', async () => {
    callMock.mockResolvedValue({ observation: null })
    await getLatestComputerObservation('run-1')
    expect(callMock).toHaveBeenCalledWith('computer.latest_observation', {
      run_id: 'run-1',
    })
  })

  it('screenshot URL 根据 observation.id 构造，本地绝对路径不进入 URL', () => {
    const id = 'a'.repeat(32)
    const url = buildComputerScreenshotUrl(id)
    expect(url).toBe(`${SERVER_URL}/computer/screenshots/${id}.png`)
    // screenshot_ref 是本地绝对路径，绝不应直接变成 src。
    expect(url).not.toContain('C:\\')
    expect(url).not.toContain('.pluto')
    expect(url).not.toContain('file://')
  })

  it('lease label 简短展示 run id', () => {
    expect(leaseLabel(null)).toBe('空闲')
    expect(
      leaseLabel({
        busy: true,
        owner_run_id: '12345678abcd',
        acquired_at: null,
        process_id: 1,
      }),
    ).toBe('由 Run 12345678 控制')
  })
})
