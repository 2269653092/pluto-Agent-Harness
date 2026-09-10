/** Automation API：全部走共享 JSON-RPC WebSocket（结构化 schedule）。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { Automation, AutomationKind } from './types'

export interface CreateAutomationInput {
  title: string
  prompt: string
  kind: AutomationKind
  run_at?: string
  interval_seconds?: number
  cron_expr?: string
  timezone?: string
  conversation_id?: string
}

/** 列出 `automations` 对应的数据或流程。 */
export async function listAutomations(): Promise<Automation[]> {
  const data = await rpcClient.call<{ automations: Automation[] }>(
    RpcMethods.automationList,
    {},
  )
  return data.automations
}

/** 获取 `automation` 对应的数据或流程。 */
export async function getAutomation(id: string): Promise<Automation> {
  const data = await rpcClient.call<{ automation: Automation }>(
    RpcMethods.automationGet,
    { automation_id: id },
  )
  return data.automation
}

/** 创建 `automation` 对应的数据或流程。 */
export async function createAutomation(
  input: CreateAutomationInput,
): Promise<Automation> {
  const data = await rpcClient.call<{ automation: Automation }>(
    RpcMethods.automationCreate,
    { ...input },
  )
  return data.automation
}

/** 执行 `pauseAutomation` 对应的界面或业务逻辑。 */
export async function pauseAutomation(id: string): Promise<Automation> {
  const data = await rpcClient.call<{ automation: Automation }>(
    RpcMethods.automationPause,
    { automation_id: id },
  )
  return data.automation
}

/** 执行 `resumeAutomation` 对应的界面或业务逻辑。 */
export async function resumeAutomation(id: string): Promise<Automation> {
  const data = await rpcClient.call<{ automation: Automation }>(
    RpcMethods.automationResume,
    { automation_id: id },
  )
  return data.automation
}

/** 取消 `automation` 对应的数据或流程。 */
export async function cancelAutomation(id: string): Promise<Automation> {
  const data = await rpcClient.call<{ automation: Automation }>(
    RpcMethods.automationCancel,
    { automation_id: id },
  )
  return data.automation
}
