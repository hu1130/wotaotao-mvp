"""Platform-level tenant client, activation code, and device administration."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import asdict
from datetime import datetime
from typing import Any

from config import DEVICE_ACTIVATION_DEFAULT_TTL_HOURS
from core.device_identity.repository import DeviceIdentityRepository
from core.redis_client import get_redis_client
from core.tenant import normalize_tenant_id
from core.tenant_admin.passwords import hash_password
from core.tenant_admin.repository import TenantAdminRepository, normalize_admin_username


logger = logging.getLogger(__name__)


class ClientAdminService:
    """Coordinate tenant console accounts, activation codes, and devices."""

    def __init__(
        self,
        *,
        tenant_admins: TenantAdminRepository | None = None,
        devices: DeviceIdentityRepository | None = None,
    ) -> None:
        self.tenant_admins = tenant_admins or TenantAdminRepository()
        self.devices = devices or DeviceIdentityRepository()

    def list_clients(self) -> list[dict[str, Any]]:
        accounts = self.tenant_admins.list_accounts(None)
        devices = self.devices.list_devices(None)
        activations = self.devices.list_activation_codes(None, 500)
        clients: dict[str, dict[str, Any]] = {}

        def item_for(tenant_id: str, tenant_name: str = "") -> dict[str, Any]:
            tenant_id = normalize_tenant_id(tenant_id)
            if tenant_id not in clients:
                clients[tenant_id] = {
                    "tenantId": tenant_id,
                    "tenantName": tenant_name or tenant_id,
                    "adminCount": 0,
                    "activeAdminCount": 0,
                    "deviceCount": 0,
                    "activeDeviceCount": 0,
                    "activationCount": 0,
                    "availableActivationCount": 0,
                    "lastDeviceSeenAt": None,
                    "createdAt": None,
                }
            elif tenant_name and clients[tenant_id]["tenantName"] == tenant_id:
                clients[tenant_id]["tenantName"] = tenant_name
            return clients[tenant_id]

        for account in accounts:
            item = item_for(account.tenant_id, account.tenant_name)
            item["adminCount"] += 1
            if account.active:
                item["activeAdminCount"] += 1
            item["createdAt"] = _earliest(item["createdAt"], account.created_at)

        for device in devices:
            item = item_for(device.tenant_id)
            item["deviceCount"] += 1
            if device.active:
                item["activeDeviceCount"] += 1
            item["lastDeviceSeenAt"] = _latest(item["lastDeviceSeenAt"], device.last_seen_at)
            item["createdAt"] = _earliest(item["createdAt"], device.created_at)

        now = datetime.now()
        for activation in activations:
            item = item_for(activation.tenant_id)
            item["activationCount"] += 1
            if activation.claimed_at is None and activation.expires_at > now:
                item["availableActivationCount"] += 1
            item["createdAt"] = _earliest(item["createdAt"], activation.created_at)

        visible_clients = [
            item
            for item in clients.values()
            if (
                item["activeAdminCount"] > 0
                or item["deviceCount"] > 0
                or item["activationCount"] > 0
            )
        ]
        return sorted(visible_clients, key=lambda item: item["tenantId"])

    def create_client(
        self,
        *,
        tenant_id: str,
        tenant_name: str,
        username: str,
        display_name: str,
        device_label: str,
        ttl_hours: int,
        reset_existing_password: bool,
        created_by: str = "client-admin-service",
    ) -> dict[str, Any]:
        tenant_id = normalize_tenant_id(tenant_id)
        username = normalize_admin_username(username)
        existing = self.tenant_admins.get_account(tenant_id, username)
        console_password = ""
        account_created = False
        password_reset = False
        if existing is None:
            console_password = _new_password()
            account = self.tenant_admins.create_account(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                username=username,
                display_name=display_name,
                password_hash=hash_password(console_password),
            )
            account_created = True
        else:
            account = existing
            if reset_existing_password:
                console_password = _new_password()
                changed = self.tenant_admins.update_password(
                    tenant_id,
                    username,
                    hash_password(console_password),
                )
                if not changed:
                    raise RuntimeError("控制台密码重置失败")
                account = self.tenant_admins.get_account(tenant_id, username) or existing
                password_reset = True

        activation = self.create_activation(
            tenant_id=tenant_id,
            label=device_label,
            ttl_hours=ttl_hours,
            created_by=created_by,
        )
        logger.warning(
            "平台管理员已创建/更新客户端: tenant=%s username=%s account_created=%s password_reset=%s activation=%s",
            tenant_id,
            username,
            account_created,
            password_reset,
            activation.get("codePrefix") or activation.get("code_prefix") or "",
        )
        return {
            "ok": True,
            "action": "createClient",
            "tenantId": tenant_id,
            "tenantName": account.tenant_name,
            "console": {
                "username": account.username,
                "displayName": account.display_name,
                "accountCreated": account_created,
                "passwordReset": password_reset,
                "password": console_password,
                "notice": "密码只在本次输出中显示，请立即安全交付给客户",
            },
            "activation": activation,
        }

    def create_activation(
        self,
        *,
        tenant_id: str,
        label: str,
        ttl_hours: int = DEVICE_ACTIVATION_DEFAULT_TTL_HOURS,
        created_by: str = "client-admin-service",
    ) -> dict[str, Any]:
        ttl_seconds = max(1, int(ttl_hours)) * 3600
        raw_code, summary = self.devices.create_activation_code(
            normalize_tenant_id(tenant_id),
            label=label,
            ttl_seconds=ttl_seconds,
            created_by=created_by,
        )
        payload = _activation_payload(summary)
        payload["activationCode"] = raw_code
        payload["ttlHours"] = max(1, int(ttl_hours))
        return payload

    def list_activations(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return [
            _activation_payload(item)
            for item in self.devices.list_activation_codes(
                normalize_tenant_id(tenant_id),
                limit,
            )
        ]

    def delete_activation(
        self, *, tenant_id: str, activation_id: int
    ) -> dict[str, Any]:
        activation = self.devices.delete_activation_code(
            tenant_id=normalize_tenant_id(tenant_id),
            activation_id=int(activation_id),
        )
        if activation is None:
            return {
                "ok": False,
                "tenantId": normalize_tenant_id(tenant_id),
                "activationId": int(activation_id),
                "deleted": False,
            }
        logger.warning(
            "平台管理员删除设备激活码: tenant=%s activation_id=%s prefix=%s",
            activation.tenant_id,
            activation.activation_id,
            activation.code_prefix,
        )
        payload = _activation_payload(activation)
        payload["deleted"] = True
        return payload

    def reset_console_password(self, *, tenant_id: str, username: str) -> dict[str, Any]:
        password = _new_password()
        changed = self.tenant_admins.update_password(
            tenant_id,
            username,
            hash_password(password),
        )
        logger.warning(
            "平台管理员重置租户控制台密码: tenant=%s username=%s changed=%s",
            normalize_tenant_id(tenant_id),
            normalize_admin_username(username),
            changed,
        )
        return {
            "ok": changed,
            "tenantId": normalize_tenant_id(tenant_id),
            "username": normalize_admin_username(username),
            "newPassword": password if changed else "",
            "sessionsInvalidated": changed,
        }

    def list_console_admins(self, tenant_id: str) -> list[dict[str, Any]]:
        return [
            {
                "tenantId": item.tenant_id,
                "tenantName": item.tenant_name,
                "username": item.username,
                "displayName": item.display_name,
                "status": item.status,
                "authVersion": item.auth_version,
                "createdAt": item.created_at,
                "lastLoginAt": item.last_login_at,
            }
            for item in self.tenant_admins.list_accounts(normalize_tenant_id(tenant_id))
        ]

    def list_devices(self, tenant_id: str) -> list[dict[str, Any]]:
        return [
            _device_payload(item)
            for item in self.devices.list_devices(normalize_tenant_id(tenant_id))
        ]

    def set_device_status(self, *, device_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "revoked"}:
            raise ValueError("status must be active or revoked")
        changed = self.devices.set_device_status(device_id, status)
        return {"ok": changed, "deviceId": device_id, "status": status}

    def delete_device(self, *, device_id: str) -> dict[str, Any]:
        device = self.devices.delete_device(device_id)
        if device is None:
            return {"ok": False, "deviceId": device_id, "deleted": False}
        sessions = purge_device_sessions(device.tenant_id, device.device_id)
        logger.warning(
            "平台管理员删除注册设备: tenant=%s device=%s sessions=%d",
            device.tenant_id,
            device.device_id,
            sessions,
        )
        return {
            "ok": True,
            "tenantId": device.tenant_id,
            "deviceId": device.device_id,
            "deleted": True,
            "redisSessionsDeleted": sessions,
        }

    def delete_client_control_plane(
        self,
        *,
        tenant_id: str,
        disable_console_admins: bool = True,
    ) -> dict[str, Any]:
        tenant_id = normalize_tenant_id(tenant_id)
        activations, devices = self.devices.purge_tenant_devices(tenant_id)
        sessions = purge_tenant_device_sessions(tenant_id)
        disabled_admins = 0
        if disable_console_admins:
            for account in self.tenant_admins.list_accounts(tenant_id):
                if self.tenant_admins.set_status(tenant_id, account.username, "disabled"):
                    disabled_admins += 1
        return {
            "ok": True,
            "tenantId": tenant_id,
            "activationCodesDeleted": activations,
            "devicesDeleted": devices,
            "redisSessionsDeleted": sessions,
            "consoleAdminsDisabled": disabled_admins,
            "businessDataDeleted": False,
            "notice": "未删除员工、考勤、人脸向量、知识库或人物记忆数据",
        }


def purge_tenant_device_sessions(tenant_id: str) -> int:
    """Delete Redis device/browser/voice session records bound to a tenant."""

    return _purge_session_payloads(tenant_id=normalize_tenant_id(tenant_id))


def purge_device_sessions(tenant_id: str, device_id: str) -> int:
    """Delete Redis device/browser/voice session records bound to one device."""

    return _purge_session_payloads(
        tenant_id=normalize_tenant_id(tenant_id),
        device_id=str(device_id or "").strip(),
    )


def _purge_session_payloads(*, tenant_id: str, device_id: str = "") -> int:
    client = get_redis_client()
    deleted = 0
    for pattern in (
        "device_avatar_bootstrap:*",
        "device_avatar_session:*",
        "voice_ticket:*",
    ):
        for key in client.scan_iter(match=pattern, count=200):
            raw = client.get(key)
            try:
                payload = json.loads(raw or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if normalize_tenant_id(str(payload.get("tenant_id") or "")) != tenant_id:
                continue
            if device_id and str(payload.get("device_id") or "") != device_id:
                continue
            deleted += int(client.delete(key) or 0)
    logger.warning(
        "设备会话已清理: tenant=%s device=%s sessions=%d",
        tenant_id,
        device_id or "*",
        deleted,
    )
    return deleted


def _activation_payload(value) -> dict[str, Any]:
    payload = asdict(value)
    result = {
        "activationId": payload["activation_id"],
        "tenantId": payload["tenant_id"],
        "codePrefix": payload["code_prefix"],
        "label": payload["label"],
        "expiresAt": payload["expires_at"],
        "claimedAt": payload["claimed_at"],
        "claimedDeviceId": payload["claimed_device_id"],
        "createdAt": payload["created_at"],
    }
    if payload.get("claimed_at") is None and payload.get("activation_code"):
        result["activationCode"] = payload["activation_code"]
    return result


def _device_payload(value) -> dict[str, Any]:
    return {
        "deviceId": value.device_id,
        "tenantId": value.tenant_id,
        "installationId": value.installation_id,
        "displayName": value.display_name,
        "status": value.status,
        "authVersion": value.auth_version,
        "createdAt": value.created_at,
        "lastSeenAt": value.last_seen_at,
    }


def _new_password() -> str:
    return secrets.token_urlsafe(18)


def _earliest(current, candidate):
    if candidate is None:
        return current
    if current is None or candidate < current:
        return candidate
    return current


def _latest(current, candidate):
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current
