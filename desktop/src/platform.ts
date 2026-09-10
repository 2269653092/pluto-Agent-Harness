/** Windows 前端平台判定：优先 Electron 注入，回退 navigator.platform。 */

export type DesktopPlatform = 'windows' | 'unknown'

/** 执行 `currentPlatform` 对应的界面或业务逻辑。 */
export function currentPlatform(): DesktopPlatform {
  const electronPlatform =
    typeof window !== 'undefined' &&
    typeof (window as { __VEST_PLATFORM__?: string }).__VEST_PLATFORM__ === 'string'
      ? (window as { __VEST_PLATFORM__?: string }).__VEST_PLATFORM__
      : undefined
  if (electronPlatform) {
    if (electronPlatform === 'win32') return 'windows'
    return 'unknown'
  }
  if (typeof navigator !== 'undefined') {
    const platform = navigator.platform.toLowerCase()
    if (platform.startsWith('win')) return 'windows'
  }
  return 'unknown'
}

/** 判断 `windows` 对应的数据或流程。 */
export function isWindows(): boolean {
  return currentPlatform() === 'windows'
}

/** 系统凭据存储的名称（密钥保存位置说明用）。 */
export function credentialStoreName(): string {
  return 'Windows 凭据管理器'
}

/** Computer Runtime 平台名（UI 展示用）。 */
export function computerPlatformName(): string {
  return 'Windows'
}
