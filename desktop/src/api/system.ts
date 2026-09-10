/** System info：Renderer 业务走 RPC system.info（GET /health 保留给 supervisor）。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'

export interface SystemInfo {
  status: string
  provider: string
  model: string
  version: string
  database: string
}

/** 获取 `system_info` 对应的数据或流程。 */
export async function getSystemInfo(): Promise<SystemInfo> {
  return rpcClient.call(RpcMethods.systemInfo, {})
}
