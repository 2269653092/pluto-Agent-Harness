"""模型 API Key 的安全存储边界。

API Key 保存在 Windows 凭据管理器，不会落盘为明文。
"""

from __future__ import annotations

from typing import Protocol


class ModelSecretStore(Protocol):
    """测试可替换的最小密钥存储接口。"""

    def get(self, provider: str) -> str | None: ...

    def set(self, provider: str, value: str) -> None: ...


class WindowsCredentialSecretStore:
    """通过 Windows 凭据管理器保存密钥（当前用户级加密，不写入项目文件）。

    密钥由 Windows 按当前用户 DPAPI 加密，进程重启后仍可读取，但不会以
    明文出现在 ``.env``、JSON 或仓库里。
    """

    target_prefix = "Pluto/model-api-key/"

    def __init__(self) -> None:
        try:
            import win32cred  # noqa: PLC0415 - 仅在 Windows 需要
        except ImportError as exc:  # pragma: no cover - 依赖缺失时显式报错
            raise RuntimeError(
                "Windows 凭据存储需要 pywin32，请安装后重试："
                "pip install pywin32"
            ) from exc
        self._win32cred = win32cred
        self._cred_type = win32cred.CRED_TYPE_GENERIC
        self._persist = win32cred.CRED_PERSIST_LOCAL_MACHINE

    def _target(self, provider: str) -> str:
        return f"{self.target_prefix}{provider}"

    def get(self, provider: str) -> str | None:
        try:
            credential = self._win32cred.CredRead(
                self._target(provider), self._cred_type
            )
        except Exception:  # noqa: BLE001 - 未找到 / 被拒绝都视为没有密钥
            return None
        blob = credential.get("CredentialBlob")
        if blob is None:
            return None
        if isinstance(blob, bytes):
            blob = blob.decode("utf-16-le", errors="replace").rstrip("\x00")
        return blob.strip() or None

    def set(self, provider: str, value: str) -> None:
        normalized = value.strip()
        if not normalized:
            raise ValueError("api key cannot be empty")
        credential = {
            "Type": self._cred_type,
            "TargetName": self._target(provider),
            "CredentialBlob": normalized,
            "Comment": "Pluto model provider API key",
            "Persist": self._persist,
            "UserName": provider,
        }
        try:
            self._win32cred.CredWrite(credential, 0)
        except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
            raise RuntimeError(
                f"Windows Credential Manager write failed: {exc}"
            ) from exc

    def delete(self, provider: str) -> None:
        """删除某个 provider 的密钥；不存在时静默返回。"""

        try:
            self._win32cred.CredDelete(self._target(provider), self._cred_type)
        except Exception:  # noqa: BLE001 - 不存在无需处理
            return


class UnavailableSecretStore:
    """没有可用系统凭据存储时的显式失败实现。"""

    def get(self, provider: str) -> str | None:
        del provider
        return None

    def set(self, provider: str, value: str) -> None:
        del provider, value
        raise RuntimeError(
            "Windows 凭据管理器不可用，请安装 pywin32 后重试，"
            "或改用 backend/.env 配置密钥"
        )


def default_secret_store() -> ModelSecretStore:
    """构建 Windows 系统凭据存储。"""

    try:
        return WindowsCredentialSecretStore()
    except RuntimeError:  # pragma: no cover - pywin32 缺失时退化为显式失败
        return UnavailableSecretStore()


__all__ = [
    "ModelSecretStore",
    "UnavailableSecretStore",
    "WindowsCredentialSecretStore",
    "default_secret_store",
]
