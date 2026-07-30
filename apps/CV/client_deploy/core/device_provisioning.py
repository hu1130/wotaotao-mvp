"""First-run activation and browser bootstrap orchestration."""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from core.device_identity import DeviceIdentity, DeviceIdentityStore
from core.device_auth_protocol import build_enrollment_proof_payload, encode_base64url


logger = logging.getLogger(__name__)


class DeviceProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisioningOutcome:
    identity: DeviceIdentity
    avatar_bootstrap_token: str
    enrolled_now: bool


class DeviceProvisioner:
    def __init__(
        self,
        server_base_url: str,
        store: DeviceIdentityStore | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.server_base_url = (server_base_url or "").rstrip("/")
        self.store = store or DeviceIdentityStore()
        self.timeout = timeout
        if (
            not urlsplit(self.server_base_url).scheme
            or not urlsplit(self.server_base_url).netloc
        ):
            raise DeviceProvisioningError("API_BASE_URL 不是有效的云端地址")

    def ensure_enrolled(
        self,
        activation_code: str = "",
        activation_code_provider=None,
    ) -> ProvisioningOutcome:
        identity = self.store.load()
        enrolled_now = False
        bootstrap_token = ""
        if identity is not None and identity.enrolled:
            if identity.server_base_url != self.server_base_url:
                raise DeviceProvisioningError(
                    "本机设备身份已绑定其他服务器；如需迁移，请先由管理员撤销并重置设备身份"
                )
        else:
            identity = self.store.load_or_create_pending(socket.gethostname())
            code = (activation_code or "").strip()
            if not code and activation_code_provider is not None:
                code = (activation_code_provider() or "").strip()
            if not code:
                raise DeviceProvisioningError("首次启动需要输入云端生成的一次性激活码")
            proof = identity.private_key.sign(
                build_enrollment_proof_payload(
                    code,
                    identity.installation_id,
                    identity.public_key_base64,
                )
            )
            response = self._json_request(
                "POST",
                "/api/v1/device-enrollment/claim",
                {
                    "activationCode": code,
                    "installationId": identity.installation_id,
                    "publicKey": identity.public_key_base64,
                    "proofSignature": encode_base64url(proof),
                    "deviceName": identity.device_name or socket.gethostname(),
                    "platformInfo": {
                        "system": platform.system(),
                        "release": platform.release(),
                        "machine": platform.machine(),
                        "python": platform.python_version(),
                        "appVersion": os.environ.get("CLIENT_APP_VERSION", "1.0.0"),
                    },
                },
            )
            data = response.get("data") or {}
            identity = self.store.mark_enrolled(
                identity,
                tenant_id=str(data.get("tenantId") or ""),
                device_id=str(data.get("deviceId") or ""),
                server_base_url=self.server_base_url,
            )
            bootstrap_token = str(data.get("avatarBootstrapToken") or "")
            enrolled_now = True
            logger.info(
                "设备首次激活完成: tenant=%s device=%s installation=%s",
                identity.tenant_id,
                identity.device_id,
                identity.installation_id,
            )

        if not bootstrap_token:
            response = self._json_request(
                "POST",
                "/api/v1/device-sessions/avatar-bootstrap",
                {},
                identity=identity,
            )
            bootstrap_token = str((response.get("data") or {}).get("token") or "")
        if not bootstrap_token:
            raise DeviceProvisioningError("云端未返回数字人启动票据")
        return ProvisioningOutcome(identity, bootstrap_token, enrolled_now)

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict,
        *,
        identity: DeviceIdentity | None = None,
    ) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CVClient/device-provisioner",
        }
        if identity is not None:
            headers.update(identity.signed_headers(method, path, body))
        request = urllib.request.Request(
            f"{self.server_base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="ignore")
            message = self._error_message(text) or f"HTTP {exc.code}"
            raise DeviceProvisioningError(f"云端设备注册失败: {message}") from exc
        except Exception as exc:
            raise DeviceProvisioningError(f"无法连接云端设备注册服务: {exc}") from exc
        try:
            result = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise DeviceProvisioningError("云端设备注册响应格式错误") from exc
        if result.get("ok") is False:
            raise DeviceProvisioningError(
                self._error_message(text) or "云端设备注册失败"
            )
        return result

    @staticmethod
    def _error_message(text: str) -> str:
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError:
            return text[:300]
        detail = payload.get("detail") or payload.get("error") or ""
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or detail)
        return str(detail)
