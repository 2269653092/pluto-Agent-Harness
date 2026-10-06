import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { rpcClient } from '../rpc'
import type { InstalledSkill } from '../api/extensions'
import { toast } from '../stores/toasts'

export default function SkillEditor({ skill, projectId, onClose }: { skill: InstalledSkill; projectId?: string; onClose: () => void }): React.JSX.Element {
  const client = useQueryClient()
  const params = { name: skill.name, scope: skill.scope, enabled: skill.enabled, project_id: projectId }
  const query = useQuery({ queryKey: ['skill-detail', projectId, skill.scope, skill.name, skill.enabled], queryFn: () => rpcClient.call<{ skill: { content: string; metadata: { description: string } }; version: string }>('skill.get', params), retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false })
  const [description, setDescription] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (query.data) { setDescription(query.data.skill.metadata.description); setContent(query.data.skill.content) } }, [query.data])
  return <section className="settings-group review-form"><h3>编辑 {skill.name}</h3><p>保留资源文件；内容修改从下一次 Run 生效。</p>
    {query.isError ? <p role="alert">{String(query.error)}</p> : null}
    <label>描述<textarea aria-label="已安装 Skill 描述" value={description} onChange={(e) => setDescription(e.target.value)} /></label>
    <label>正文<textarea aria-label="已安装 Skill 正文" rows={12} value={content} onChange={(e) => setContent(e.target.value)} /></label>
    {error ? <p role="alert">{error}</p> : null}
    <div className="review-actions"><button className="btn btn-primary" disabled={busy || !query.data} onClick={() => {
      setBusy(true); setError('')
      void rpcClient.call('skill.update', { ...params, description, instructions: content, expected_version: query.data!.version })
        .then(async () => { await client.invalidateQueries({ queryKey: ['extensions'] }); toast.success('Skill 已更新'); onClose() })
        .catch((reason) => setError(String(reason))).finally(() => setBusy(false))
    }}>保存修改</button><button className="btn" disabled={busy} onClick={onClose}>关闭</button></div>
  </section>
}
