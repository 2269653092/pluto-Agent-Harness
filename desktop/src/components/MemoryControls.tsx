import { useState } from 'react'
import { editMemory } from '../api/memories'
import type { LongTermMemory, LongTermMemoryOverview } from '../api/types'
import { toast } from '../stores/toasts'
import { ConfirmDialog } from './ConfirmDialog'

export function MemoryControls({ memory, projectId, onChanged }: { memory: LongTermMemory; projectId?: string; onChanged: () => void }): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(memory)
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const act = async (action: string): Promise<void> => {
    setBusy(true); setError('')
    try {
      await editMemory({ project_id: projectId, scope: 'project', memory_id: memory.id, expected_revision: action === 'edit' ? form.revision : memory.revision,
        action, title: form.title, summary: form.summary, content: form.content, confirmed: action === 'delete' })
      setEditing(false); setDeleting(false); onChanged()
      toast.success(action === 'edit' ? '记忆已更新' : action === 'restore' ? '记忆已恢复' : action === 'archive' ? '记忆已归档' : '记忆已删除')
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }
  return <div className="memory-controls">
    {memory.source ? <details><summary>记忆来源</summary>{Object.entries(memory.source).map(([key, value]) => <p key={key}>{key}: {value}</p>)}</details> : null}
    {editing ? <div className="review-form"><label>标题<input aria-label="记忆标题" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
      <label>召回摘要<textarea aria-label="记忆摘要" value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></label>
      <label>完整正文<textarea aria-label="记忆正文" rows={6} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></label>
      <button className="btn" disabled={busy} onClick={() => void act('edit')}>保存记忆</button><button className="btn" disabled={busy} onClick={() => setEditing(false)}>取消</button></div> : null}
    <div className="review-actions">{memory.status === 'active' ? <><button className="btn btn-sm" disabled={busy} onClick={() => { setForm(memory); setEditing(true) }}>编辑</button><button className="btn btn-sm" disabled={busy} onClick={() => void act('archive')}>归档</button></> : <button className="btn btn-sm" disabled={busy} onClick={() => void act('restore')}>恢复</button>}
      <button className="btn btn-sm btn-danger" disabled={busy} onClick={() => setDeleting(true)}>删除</button></div>
    {error ? <p role="alert">{error}</p> : null}
    <ConfirmDialog open={deleting} title={`删除记忆 ${memory.title}？`} message="删除后不再召回；原文件保留在本地 deleted 目录，便于回滚。" confirmLabel="删除" busy={busy} onConfirm={() => void act('delete')} onCancel={() => setDeleting(false)} />
  </div>
}

export function PreferenceControls({ data, onChanged }: { data: LongTermMemoryOverview; onChanged: () => void }): React.JSX.Element {
  const [editing, setEditing] = useState<string | null>(null)
  const [editVersion, setEditVersion] = useState(data.core_version)
  const [value, setValue] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = async (key: string, action: 'edit' | 'delete'): Promise<void> => {
    setBusy(true); setError('')
    try { await editMemory({ scope: 'user', key, value, action, expected_version: action === 'edit' ? editVersion : data.core_version, confirmed: action === 'delete' }); setEditing(null); setDeleting(null); onChanged(); toast.success('用户偏好已更新') }
    catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }
  return <div>{data.preferences?.map((entry) => <article className="preference-row" id={`memory-${entry.key}`} key={entry.key}>
    <strong>{entry.key}</strong><p>{entry.value}</p><details><summary>来源与更新日期</summary><p>{entry.source_statement}</p><small>{entry.reason} · {entry.updated_at}</small></details>
    {editing === entry.key ? <div className="review-form"><textarea aria-label="用户偏好内容" value={value} onChange={(e) => setValue(e.target.value)} /><button className="btn" disabled={busy} onClick={() => void save(entry.key, 'edit')}>保存偏好</button><button className="btn" disabled={busy} onClick={() => setEditing(null)}>取消</button></div> : null}
    <button className="btn btn-sm" disabled={busy} onClick={() => { setEditing(entry.key); setValue(entry.value); setEditVersion(data.core_version) }}>修改偏好</button><button className="btn btn-sm btn-danger" disabled={busy} onClick={() => setDeleting(entry.key)}>删除偏好</button>
  </article>)}{error ? <p role="alert">{error}</p> : null}<ConfirmDialog open={Boolean(deleting)} title="删除用户偏好？" message="删除后，此偏好不再进入新的运行上下文。" confirmLabel="删除" busy={busy} onConfirm={() => { if (deleting) void save(deleting, 'delete') }} onCancel={() => setDeleting(null)} /></div>
}

export function LegacyPreferenceControls({ data, onChanged }: { data: LongTermMemoryOverview; onChanged: () => void }): React.JSX.Element | null {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [version, setVersion] = useState(data.core_version)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!data.legacy_core?.trim()) return null
  return <section className="review-form"><h4>迁移前的用户偏好</h4><p>保留原文，不推测或拆分旧偏好；修改不会影响按 key 管理的新条目。</p>
    {editing ? <><textarea aria-label="旧用户偏好" rows={6} value={value} onChange={(event) => setValue(event.target.value)} />
      <button className="btn" disabled={busy} onClick={() => {
        setBusy(true); setError('')
        void editMemory({ scope: 'user', action: 'edit_legacy', value, expected_version: version })
          .then(() => { setEditing(false); onChanged(); toast.success('旧偏好已更新') })
          .catch((reason) => setError(String(reason))).finally(() => setBusy(false))
      }}>保存旧偏好</button><button className="btn" disabled={busy} onClick={() => setEditing(false)}>取消</button></> :
      <button className="btn" onClick={() => { setValue(data.legacy_core ?? ''); setVersion(data.core_version); setEditing(true) }}>编辑旧偏好</button>}
    {error ? <p role="alert">{error}</p> : null}
  </section>
}
