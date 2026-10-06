import type { SkillCandidate } from '../api/types'

export default function SkillDiscoveryCard({ candidate, onReview, onDismiss }: {
  candidate: SkillCandidate; onReview: () => void; onDismiss: () => void
}): React.JSX.Element | null {
  if (candidate.origin !== 'pattern_mining' || candidate.status !== 'pending' || candidate.dismissed) return null
  return <article className="skill-discovery-card" data-candidate-id={candidate.id}>
    <h3>发现一个可复用流程</h3><strong>{candidate.proposed_name}</strong><p>{candidate.description}</p>
    <small>来自 {candidate.source_task_ids.length} 个相似任务 · 当前项目 · 待审核</small>
    <div className="review-actions"><button className="btn btn-primary" onClick={onReview}>查看草稿</button>
      <button className="btn" onClick={onDismiss}>稍后处理</button></div>
  </article>
}
