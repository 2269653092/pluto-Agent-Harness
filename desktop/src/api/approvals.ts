/** Approval API：全部走共享 JSON-RPC WebSocket（approve / deny 只执行一次）。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { ApprovalRequest, ApprovalStatus } from './types'

/** 列出 `approvals` 对应的数据或流程。 */
export async function listApprovals(
  status?: ApprovalStatus,
  limit = 50,
): Promise<ApprovalRequest[]> {
  const data = await rpcClient.call<{ approvals: ApprovalRequest[] }>(
    RpcMethods.approvalList,
    status ? { status, limit } : { limit },
  )
  return data.approvals
}

/** 获取 `approval` 对应的数据或流程。 */
export async function getApproval(id: string): Promise<ApprovalRequest> {
  const data = await rpcClient.call<{ approval: ApprovalRequest }>(
    RpcMethods.approvalGet,
    { approval_id: id },
  )
  return data.approval
}

/** 批准 `approval` 对应的数据或流程。 */
export async function approveApproval(id: string): Promise<ApprovalRequest> {
  const data = await rpcClient.call<{ approval: ApprovalRequest }>(
    RpcMethods.approvalApprove,
    { approval_id: id },
  )
  return data.approval
}

/** 拒绝 `approval` 对应的数据或流程。 */
export async function denyApproval(id: string): Promise<ApprovalRequest> {
  const data = await rpcClient.call<{ approval: ApprovalRequest }>(
    RpcMethods.approvalDeny,
    { approval_id: id },
  )
  return data.approval
}
