/** Task API：全部走共享 JSON-RPC WebSocket（Plan Mode V1 最小接口）。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'
import type { Task } from './types'

/** 列出 `tasks` 对应的数据或流程。 */
export async function listTasks(conversationId: string, limit = 20): Promise<Task[]> {
  const data = await rpcClient.call<{ tasks: Task[] }>(RpcMethods.taskList, {
    conversation_id: conversationId,
    limit,
  })
  return data.tasks
}

/** 获取 `task` 对应的数据或流程。 */
export async function getTask(taskId: string): Promise<Task> {
  const data = await rpcClient.call<{ task: Task }>(RpcMethods.taskGet, {
    task_id: taskId,
  })
  return data.task
}

/** 执行 `planAccept` 对应的界面或业务逻辑。 */
export async function planAccept(taskId: string): Promise<Task> {
  const data = await rpcClient.call<{ task: Task }>(RpcMethods.taskPlanAccept, {
    task_id: taskId,
  })
  return data.task
}

/** 执行 `planReject` 对应的界面或业务逻辑。 */
export async function planReject(taskId: string): Promise<Task> {
  const data = await rpcClient.call<{ task: Task }>(RpcMethods.taskPlanReject, {
    task_id: taskId,
  })
  return data.task
}
