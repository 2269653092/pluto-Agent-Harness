import { useQuery, useQueryClient } from '@tanstack/react-query'
import { listProjects, registerProject } from '../api/projects'
import { toast } from '../stores/toasts'

export default function ProjectPicker({ value, onChange, disabled = false }: {
  value?: string; onChange: (id: string) => void; disabled?: boolean
}): React.JSX.Element {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['projects'], queryFn: listProjects, retry: false })
  const selectFolder = async (): Promise<void> => {
    const path = window.pluto?.selectProjectFolder
      ? await window.pluto.selectProjectFolder() : window.prompt('输入已存在的项目文件夹绝对路径')
    if (!path) return
    try {
      const { project } = await registerProject(path)
      await client.invalidateQueries({ queryKey: ['projects'] })
      onChange(project.id)
    } catch (error) { toast.error(String(error)) }
  }
  return <div className="project-picker">
    <label>项目 <select aria-label="当前项目" disabled={disabled || !query.data}
      value={value || query.data?.default_project_id || ''} onChange={(event) => onChange(event.target.value)}>
      {query.data?.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <button className="btn" disabled={disabled} onClick={() => void selectFolder()}>选择项目文件夹</button>
  </div>
}
