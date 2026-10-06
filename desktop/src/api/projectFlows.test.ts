import { beforeEach, describe, expect, it, vi } from 'vitest'
const { callMock } = vi.hoisted(() => ({ callMock: vi.fn() }))
vi.mock('../rpc', () => ({ rpcClient: { call: callMock } }))
import { listProjects, registerProject } from './projects'
import { editMemory, listMemories } from './memories'
import { acceptSkillCandidate, editSkillCandidate, listSkillCandidates, setSkillLearningEnabled } from './skillLearning'
import type { SkillCandidate } from './types'

describe('scoped project management RPC contracts', () => {
  beforeEach(() => { callMock.mockReset(); callMock.mockResolvedValue({}) })
  it('registers an absolute folder and queries persisted projects', async () => {
    await listProjects(); await registerProject('C:/projects/b')
    expect(callMock).toHaveBeenCalledWith('project.list', {})
    expect(callMock).toHaveBeenCalledWith('project.register', { path: 'C:/projects/b' })
  })
  it('queries memory by project and sends CAS edits', async () => {
    await listMemories('project-b')
    await editMemory({ scope: 'project', project_id: 'project-b', memory_id: 'M001', expected_revision: 3, action: 'archive' })
    expect(callMock).toHaveBeenCalledWith('memory.list', { project_id: 'project-b' })
    expect(callMock).toHaveBeenCalledWith('memory.edit', expect.objectContaining({ project_id: 'project-b', expected_revision: 3 }))
  })
  it('restores cards by conversation and dismisses a candidate without rejecting it', async () => {
    await listSkillCandidates('project-b', 'conversation-b')
    await editSkillCandidate({ id: 'draft', project_id: 'project-b', revision: 7 } as SkillCandidate, { action: 'dismiss' })
    expect(callMock).toHaveBeenCalledWith('skill_learning.list', { project_id: 'project-b', conversation_id: 'conversation-b' })
    expect(callMock).toHaveBeenCalledWith('skill_learning.edit', { candidate_id: 'draft', project_id: 'project-b', expected_revision: 7, action: 'dismiss' })
  })
  it('accepts the edited user scope and revision, and keeps learning switch separate', async () => {
    await acceptSkillCandidate('draft', { scope: 'user', project_id: 'project-b', expected_revision: 8 })
    await setSkillLearningEnabled(false)
    expect(callMock).toHaveBeenCalledWith('skill_learning.accept', { candidate_id: 'draft', scope: 'user', project_id: 'project-b', expected_revision: 8, confirmed: true })
    expect(callMock).toHaveBeenCalledWith('skill_learning.settings', { enabled: false })
  })
})
