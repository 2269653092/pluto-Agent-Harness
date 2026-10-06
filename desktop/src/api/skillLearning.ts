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
  options?: { project_id?: string; scope?: 'user' | 'project'; expected_revision?: number },
): Promise<{ candidate: SkillCandidate; path: string | null }> {
  return rpcClient.call(RpcMethods.skillLearningAccept, {
    candidate_id: candidateId,
    scope: 'project',
    confirmed: true,
    ...options,
  })
}

/** 拒绝待审核 Skill Candidate。 */
export function rejectSkillCandidate(
  candidateId: string,
  options?: { project_id?: string; expected_revision?: number },
): Promise<{ candidate: SkillCandidate }> {
  return rpcClient.call(RpcMethods.skillLearningReject, {
    candidate_id: candidateId,
    ...options,
  })
}

export interface CandidateList { candidates: SkillCandidate[]; enabled: boolean; scan: { last_error?: string | null; inflight?: { attempt: number } | null } }
export function listSkillCandidates(projectId?: string, conversationId?: string): Promise<CandidateList> {
  return rpcClient.call('skill_learning.list', { project_id: projectId, conversation_id: conversationId })
}
export function getSkillCandidate(id: string, projectId?: string): Promise<{ candidate: SkillCandidate; markdown: string; diff: string; tasks: { id: string; title: string; goal: string | null }[] }> {
  return rpcClient.call('skill_learning.get', { candidate_id: id, project_id: projectId })
}
export function editSkillCandidate(candidate: SkillCandidate, fields: Record<string, unknown>): Promise<{ candidate: SkillCandidate }> {
  return rpcClient.call('skill_learning.edit', { candidate_id: candidate.id, project_id: candidate.project_id, expected_revision: candidate.revision ?? 1, ...fields })
}
export function setSkillLearningEnabled(enabled: boolean): Promise<{ enabled: boolean }> {
  return rpcClient.call('skill_learning.settings', { enabled })
}
