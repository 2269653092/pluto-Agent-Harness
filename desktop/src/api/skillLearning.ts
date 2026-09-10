/** 桌面端单任务 Skill 生成与人工审核 API。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { GenerateSkillResponse, SkillCandidate } from './types'

/** 从当前任务的已有执行记录生成待审核 Skill Candidate。 */
export function generateSkillFromTask(taskId: string): Promise<GenerateSkillResponse> {
  return rpcClient.call(
    RpcMethods.skillLearningGenerate,
    { task_id: taskId },
    { timeoutMs: 0 },
  )
}

/** 确认候选并将其保存为项目级正式 Skill。 */
export function acceptSkillCandidate(
  candidateId: string,
): Promise<{ candidate: SkillCandidate; path: string | null }> {
  return rpcClient.call(RpcMethods.skillLearningAccept, {
    candidate_id: candidateId,
    scope: 'project',
    confirmed: true,
  })
}

/** 拒绝待审核 Skill Candidate。 */
export function rejectSkillCandidate(
  candidateId: string,
): Promise<{ candidate: SkillCandidate }> {
  return rpcClient.call(RpcMethods.skillLearningReject, {
    candidate_id: candidateId,
  })
}
