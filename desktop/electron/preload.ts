import { contextBridge, ipcRenderer } from 'electron'

export type DesktopNotificationKind = 'approval' | 'run' | 'artifact'

export interface DesktopNotification {
  title: string
  body: string
  kind: DesktopNotificationKind
}

// preload 只暴露真正需要的最小 Desktop API；业务 RPC 不经过 Electron Main。
// Renderer 通过 WS /rpc 与 localhost Pluto Host 通信，媒体使用只读 HTTP transport。
const desktopApi = {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome,
  },
  /** 打开 `external` 对应的数据或流程。 */
  openExternal: (url: string): Promise<boolean> =>
    ipcRenderer.invoke('pluto:open-external', url) as Promise<boolean>,
  /** 通知当前对象的相关流程。 */
  notify: (notification: DesktopNotification): void => {
    ipcRenderer.send('pluto:notify', notification)
  },
  /** 设置 `approval_visible` 对应的数据或流程。 */
  setApprovalVisible: (visible: boolean): void => {
    ipcRenderer.send('pluto:approval-set-visible', visible)
  },
  /** 设置 `approval_size` 对应的数据或流程。 */
  setApprovalSize: (height: number): void => {
    ipcRenderer.send('pluto:approval-set-size', height)
  },
} as const

contextBridge.exposeInMainWorld('pluto', desktopApi)

export type DesktopApi = typeof desktopApi
