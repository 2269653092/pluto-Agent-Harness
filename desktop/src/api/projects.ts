import { rpcClient } from '../rpc'
export interface Project { id: string; name: string; path: string }
export function listProjects(): Promise<{ projects: Project[]; default_project_id: string }> {
  return rpcClient.call('project.list', {})
}
export function registerProject(path: string): Promise<{ project: Project }> {
  return rpcClient.call('project.register', { path })
}
