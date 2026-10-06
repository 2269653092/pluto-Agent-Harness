/** 项目记忆查询和带版本校验的用户管理 API。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { LongTermMemoryOverview } from './types'

/** 列出 `memories` 对应的数据或流程。 */
export async function listMemories(projectId?: string): Promise<LongTermMemoryOverview> {
  return rpcClient.call<LongTermMemoryOverview>(RpcMethods.memoryList, projectId ? { project_id: projectId } : {})
}

export function editMemory(params: Record<string, unknown>): Promise<unknown> {
  return rpcClient.call('memory.edit', params)
}
