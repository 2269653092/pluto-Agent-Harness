/** 长期记忆只读 API：Desktop 只观察，不绕过 Agent/Harness 写入边界。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { LongTermMemoryOverview } from './types'

/** 列出 `memories` 对应的数据或流程。 */
export async function listMemories(): Promise<LongTermMemoryOverview> {
  return rpcClient.call<LongTermMemoryOverview>(RpcMethods.memoryList, {})
}
