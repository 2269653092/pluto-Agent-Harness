import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { SkillCandidate, LongTermMemory } from '../api/types'
import SkillDiscoveryCard from './SkillDiscoveryCard'
import SkillLearningPanel from './SkillLearningPanel'
import ProjectPicker from './ProjectPicker'
import { MemoryControls, PreferenceControls } from './MemoryControls'

const draft: SkillCandidate = {
  id: 'candidate-1', project_id: 'project-a', scope: 'project', revision: 2, origin: 'pattern_mining', action: 'create',
  proposed_name: 'api-check', description: '检查接口', reason: '重复流程', procedure: ['读取接口', '验证业务结果'],
  pitfalls: ['不能只验证 HTTP 200'], verification: ['业务断言通过'], source_task_ids: ['a', 'b', 'c', 'd', 'e'],
  source_run_ids: [], source_conversation_id: 'conversation-a', source_tool_call_id: null, existing_skill_name: null,
  status: 'pending', created_at: '2026-01-01T00:00:00Z', reviewed_at: null, evidence_summary: '五次有效执行',
}
function renderWithCache(client: QueryClient, element: React.JSX.Element): string {
  return renderToStaticMarkup(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
}
describe('project-scoped review and memory components', () => {
  it('discovery card exposes review/defer without installing the draft', () => {
    const html = renderToStaticMarkup(<SkillDiscoveryCard candidate={draft} onReview={vi.fn()} onDismiss={vi.fn()} />)
    expect(html).toContain('发现一个可复用流程')
    expect(html).toContain('5 个相似任务')
    expect(html).toContain('查看草稿')
    expect(html).toContain('稍后处理')
    expect(html).not.toContain('接受并安装')
  })
  it.each([{ dismissed: true }, { status: 'accepted' as const }, { origin: 'manual_task' as const }])('only pending automatic visible cards render: %j', (changes) => {
    expect(renderToStaticMarkup(<SkillDiscoveryCard candidate={{ ...draft, ...changes }} onReview={vi.fn()} onDismiss={vi.fn()} />)).toBe('')
  })
  it('settings restores a persisted draft and displays evidence, editable scope and suppression', () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(['skill-candidates', 'project-a'], { candidates: [draft, { ...draft, id: 'rejected-1', status: 'rejected', suppressed: true }], enabled: false, scan: { last_error: 'offline' } })
    client.setQueryData(['skill-candidate', 'project-a', draft.id], { candidate: draft, tasks: [{ id: 'a', title: '检查接口任务', goal: '验证业务结果' }], markdown: '', diff: '' })
    const html = renderWithCache(client, <SkillLearningPanel projectId="project-a" candidateId={draft.id} />)
    for (const text of ['待审核 Skills (1)', '五次有效执行', '草稿名称', 'procedure', 'verification', '用户级（跨项目）', '生成最终文件预览与差异', '接受并安装', '恢复推荐', '重新分析']) expect(html).toContain(text)
    expect(html).toContain('自动学习')
  })
  it('project picker uses the persisted project selection', () => {
    const client = new QueryClient()
    client.setQueryData(['projects'], { default_project_id: 'project-a', projects: [{ id: 'project-a', name: '默认工作区', path: 'C:/a' }, { id: 'project-b', name: '项目 B', path: 'C:/b' }] })
    const html = renderWithCache(client, <ProjectPicker value="project-b" onChange={vi.fn()} />)
    expect(html).toContain('value="project-b" selected')
    expect(html).toContain('选择项目文件夹')
  })
  it('memory actions separate active/archived memories and expose preference provenance', () => {
    const memory: LongTermMemory = { id: 'M001', title: '接口决策', summary: '约定', content: 'REST', status: 'archived', revision: 3,
      created_at: '2026-01-01', updated_at: '2026-01-01', last_accessed_at: '2026-01-01', access_count: 0,
      last_update_reason: null, archive_reason: '用户归档', source: { statement: '本项目使用 REST' } }
    const html = renderToStaticMarkup(<MemoryControls memory={memory} projectId="project-a" onChanged={vi.fn()} />)
    expect(html).toContain('恢复')
    expect(html).not.toContain('>归档<')
    expect(html).toContain('本项目使用 REST')
    const preferences = renderToStaticMarkup(<PreferenceControls data={{ core: '', core_version: 'v1', active: [], archived: [], active_count: 0, max_active: 25,
      preferences: [{ key: 'communication.language', value: '中文', reason: '明确偏好', source_statement: '以后默认中文', updated_at: '2026-01-01' }] }} onChanged={vi.fn()} />)
    expect(preferences).toContain('以后默认中文')
    expect(preferences).toContain('修改偏好')
    expect(preferences).toContain('删除偏好')
  })
})
