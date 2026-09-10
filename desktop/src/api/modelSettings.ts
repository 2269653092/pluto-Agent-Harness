/** 模型设置：非敏感配置由 Host 落盘，API Key 保存到 Windows 凭据管理器。 */

import { rpcClient } from '../rpc'
import { RpcMethods } from '../rpc/methods'

export type ModelProvider = 'openai' | 'qwen' | 'deepseek' | 'anthropic'
export type ApiStyle = 'responses' | 'chat_completions' | 'anthropic_messages'

export interface ProviderModelSettings {
  provider: ModelProvider
  label: string
  model: string
  base_url: string | null
  api_style: ApiStyle
  configured: boolean
  key_source: 'credential_store' | 'environment' | 'none'
}

export interface ProviderModelSettingsUpdate {
  provider: ModelProvider
  model: string
  base_url: string | null
  api_style: ApiStyle
  api_key?: string | null
}

export interface ModelRoleSettings {
  enabled: boolean
  inherit_main: boolean
  provider: ModelProvider | null
  model: string | null
}

export interface ActiveModelRole {
  enabled: boolean
  provider: string | null
  model: string | null
}

export interface ModelSettingsView {
  default_provider: ModelProvider
  providers: ProviderModelSettings[]
  reflection: ModelRoleSettings
  maintenance: ModelRoleSettings
  summary: ModelRoleSettings
  active_provider: string
  active_model: string
  active_roles: Record<'main' | 'summary' | 'reflection' | 'maintenance', ActiveModelRole>
  restart_required: boolean
  restart_supported: boolean
  restart_blocked_by_run_ids: string[]
  can_restart: boolean
}

export interface ModelSettingsUpdate {
  default_provider: ModelProvider
  providers: ProviderModelSettingsUpdate[]
  reflection: ModelRoleSettings
  maintenance: ModelRoleSettings
  summary: ModelRoleSettings
}

export interface ModelConnectionResult {
  success: boolean
  provider: string
  model: string
  duration_ms: number
}

/** 获取 `model_settings` 对应的数据或流程。 */
export function getModelSettings(): Promise<ModelSettingsView> {
  return rpcClient.call(RpcMethods.modelSettingsGet, {})
}

/** 更新 `model_settings` 对应的数据或流程。 */
export function updateModelSettings(input: ModelSettingsUpdate): Promise<ModelSettingsView> {
  return rpcClient.call(RpcMethods.modelSettingsUpdate, { ...input })
}

/** 执行 `testModelConnection` 对应的界面或业务逻辑。 */
export function testModelConnection(
  input: ProviderModelSettingsUpdate,
): Promise<ModelConnectionResult> {
  return rpcClient.call(RpcMethods.modelSettingsTest, { ...input })
}

/** 执行 `restartHost` 对应的界面或业务逻辑。 */
export function restartHost(): Promise<{ accepted: boolean }> {
  return rpcClient.call(RpcMethods.systemRestart, {})
}
