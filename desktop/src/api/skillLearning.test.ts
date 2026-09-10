/** 桌面端 Skill Learning RPC 参数测试。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))

vi.mock('../rpc', () => ({
  rpcClient: { call: callMock },
}))

import {
  acceptSkillCandidate,
  generateSkillFromTask,
  rejectSkillCandidate,
} from './skillLearning'

describe('skill learning desktop api', () => {
  beforeEach(() => {
    callMock.mockReset()
  })

  it('生成请求使用无超时 RPC', async () => {
    callMock.mockResolvedValue({ candidate: null, created: false, message: '无候选' })
    await generateSkillFromTask('task-1')
    expect(callMock).toHaveBeenCalledWith(
      'skill_learning.generate',
      { task_id: 'task-1' },
      { timeoutMs: 0 },
    )
  })

  it('接受候选时携带项目 scope 和明确确认', async () => {
    callMock.mockResolvedValue({ candidate: { id: 'candidate-1' }, path: 'SKILL.md' })
    await acceptSkillCandidate('candidate-1')
    expect(callMock).toHaveBeenCalledWith('skill_learning.accept', {
      candidate_id: 'candidate-1',
      scope: 'project',
      confirmed: true,
    })
  })

  it('拒绝候选调用 reject RPC', async () => {
    callMock.mockResolvedValue({ candidate: { id: 'candidate-1' } })
    await rejectSkillCandidate('candidate-1')
    expect(callMock).toHaveBeenCalledWith('skill_learning.reject', {
      candidate_id: 'candidate-1',
    })
  })
})
