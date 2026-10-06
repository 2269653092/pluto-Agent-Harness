import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { acceptSkillCandidate, rejectSkillCandidate, listSkillCandidates, getSkillCandidate, editSkillCandidate, setSkillLearningEnabled } from '../api/skillLearning'
import type { SkillCandidate } from '../api/types'
import { toast } from '../stores/toasts'
import { rpcClient } from '../rpc'

export default function SkillLearningPanel({ projectId, candidateId }: { projectId?: string; candidateId?: string }): React.JSX.Element {
  const client = useQueryClient()
  const [selected, setSelected] = useState(candidateId ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<{ markdown: string; diff: string } | null>(null)
  const query = useQuery({ queryKey: ['skill-candidates', projectId], queryFn: () => listSkillCandidates(projectId), refetchInterval: 5000, retry: false })
  const detail = useQuery({ queryKey: ['skill-candidate', projectId, selected], queryFn: () => getSkillCandidate(selected, projectId), enabled: Boolean(selected), retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false })
  const [form, updateForm] = useState<SkillCandidate | null>(detail.data?.candidate ?? null)
  const [dirty, setDirty] = useState(false)
  const setForm = (next: SkillCandidate): void => { setDirty(true); setPreview(null); updateForm(next) }
  useEffect(() => { setSelected(candidateId ?? ''); updateForm(null); setDirty(false); setPreview(null) }, [candidateId, projectId])
  useEffect(() => { if (!dirty || form?.id !== detail.data?.candidate.id) updateForm(detail.data?.candidate ?? null) }, [detail.data, dirty, form?.id])
  const refresh = async (): Promise<void> => {
    await Promise.all([client.invalidateQueries({ queryKey: ['skill-candidates'] }), client.invalidateQueries({ queryKey: ['skill-candidate'] }), client.invalidateQueries({ queryKey: ['extensions'] })])
  }
  const act = async (action: 'save' | 'accept' | 'reject' | 'restore'): Promise<void> => {
    if (!form) return
    setBusy(true); setError('')
    try {
      if (action === 'restore') await editSkillCandidate(form, { action: 'restore_recommendation' })
      else if (action === 'reject') await rejectSkillCandidate(form.id, { project_id: projectId, expected_revision: form.revision })
      else {
        const { candidate } = await editSkillCandidate(form, { proposed_name: form.proposed_name, description: form.description, procedure: form.procedure, pitfalls: form.pitfalls, verification: form.verification, scope: form.scope ?? 'project' })
        updateForm(candidate)
        if (action === 'accept') await acceptSkillCandidate(candidate.id, { project_id: projectId, scope: candidate.scope, expected_revision: candidate.revision })
      }
      toast.success(action === 'accept' ? '审核通过，下次运行可使用此 Skill' : action === 'save' ? '草稿已保存' : action === 'restore' ? '已恢复流程推荐' : '已拒绝并暂停此流程推荐')
      setDirty(false)
      await refresh()
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }
  const pending = query.data?.candidates.filter((c) => c.status === 'pending') ?? []
  const suppressed = query.data?.candidates.filter((c) => c.suppressed) ?? []
  return <section className="settings-group skill-review">
    <header className="settings-group__header"><div><h3>待审核 Skills ({pending.length})</h3><p>自动学习只生成指令草稿，审核前不会进入 Agent 的技能目录。</p></div>
      <label><input type="checkbox" aria-label="自动发现 Skill" checked={query.data?.enabled ?? true} onChange={(e) => {
        void setSkillLearningEnabled(e.target.checked).then(refresh).catch((reason) => toast.error(String(reason)))
      }} />自动发现</label>
    </header>
    {query.isError ? <p role="alert">{String(query.error)} <button className="btn" onClick={() => void query.refetch()}>重试</button></p> : null}
    {query.data?.scan.last_error ? <p role="status">后台分析未完成：{query.data.scan.last_error}。已保存重试状态，不影响当前任务。<button className="btn" onClick={() => {
      void rpcClient.call('skill_learning.settings', { project_id: projectId, retry: true }).then(refresh).catch((reason) => toast.error(String(reason)))
    }}>重新分析</button></p> : null}
    <div className="review-candidates">{pending.map((candidate) => <button className="btn" key={candidate.id} onClick={() => { if (!dirty || window.confirm('放弃未保存的草稿修改？')) { setDirty(false); setSelected(candidate.id); setPreview(null) } }}>
      {candidate.proposed_name} · {candidate.origin === 'pattern_mining' ? '自动学习' : '手动创建'} · {candidate.source_task_ids.length} 个任务
    </button>)}</div>
    {!pending.length ? <p>暂无待审核草稿</p> : null}
    {detail.isError ? <p role="alert">{String(detail.error)}</p> : null}
    {form ? <div className="review-form" key={selected}>
      <h4>{form.status === 'pending' ? '审核草稿' : '审核记录'} · {form.proposed_name}</h4>
      <p>生成理由：{form.reason}</p><p>证据：{form.evidence_summary}</p>
      <details><summary>查看来源任务 ({form.source_task_ids.length})</summary>{detail.data?.tasks.map((task) => <p key={task.id}>{task.title} · {task.goal}<br /><code>{task.id}</code></p>)}</details>
      <label>名称<input aria-label="草稿名称" disabled={busy || form.status !== 'pending'} value={form.proposed_name} onChange={(e) => setForm({ ...form, proposed_name: e.target.value })} /></label>
      <label>用途描述<textarea aria-label="草稿描述" disabled={busy || form.status !== 'pending'} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
      {(['procedure', 'pitfalls', 'verification'] as const).map((key, i) => <label key={key}>{['步骤（每行一项）', '注意事项（每行一项）', '验证方法（每行一项）'][i]}
        <textarea aria-label={key} rows={4} disabled={busy || form.status !== 'pending'} value={form[key].join('\n')} onChange={(e) => setForm({ ...form, [key]: e.target.value.split('\n') })} />
      </label>)}
      <label>作用域<select aria-label="Skill 作用域" disabled={form.action === 'update' || busy || form.status !== 'pending'} value={form.scope ?? 'project'} onChange={(e) => setForm({ ...form, scope: e.target.value as 'project' | 'user' })}><option value="project">当前项目</option><option value="user">用户级（跨项目）</option></select></label>
      {detail.data?.diff ? <details><summary>与当前 Skill 的差异（已保存版本）</summary><pre>{detail.data.diff}</pre></details> : null}
      {error ? <p role="alert">{error} <button className="btn" disabled={busy} onClick={() => {
        if (!dirty || window.confirm('放弃未保存修改并读取最新草稿？')) { setDirty(false); void detail.refetch() }
      }}>读取最新版本</button></p> : null}
      {form.status === 'pending' ? <div className="review-actions"><button className="btn" disabled={busy} onClick={() => void act('save')}>保存草稿</button><button className="btn btn-primary" disabled={busy} onClick={() => void act('accept')}>接受并安装</button><button className="btn btn-danger" disabled={busy} onClick={() => void act('reject')}>拒绝</button></div> : null}
    </div> : null}
    {form ? <div><button className="btn" disabled={busy} onClick={() => {
      void rpcClient.call<{ markdown: string; diff: string }>('skill_learning.get', { candidate_id: form.id, project_id: projectId, draft: form })
        .then(setPreview).catch((reason) => setError(String(reason)))
    }}>生成最终文件预览与差异</button>{preview ? <details open><summary>后端校验的最终 SKILL.md</summary><pre>{preview.markdown}</pre>{preview.diff ? <pre>{preview.diff}</pre> : null}</details> : null}</div> : null}
    {suppressed.length ? <details><summary>已暂停推荐的流程 ({suppressed.length})</summary>{suppressed.map((candidate) => <p key={candidate.id}>{candidate.proposed_name} <button className="btn" onClick={() => {
      void editSkillCandidate(candidate, { action: 'restore_recommendation' }).then(refresh).catch((reason) => toast.error(String(reason)))
    }}>恢复推荐</button></p>)}</details> : null}
  </section>
}
