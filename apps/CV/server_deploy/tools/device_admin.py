"""Manage one-time activation codes and registered frontdesk devices."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEVICE_ACTIVATION_DEFAULT_TTL_HOURS
from core.device_identity.repository import DeviceIdentityRepository
from core.redis_client import get_redis_client
from core.tenant import normalize_tenant_id


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _print(payload: dict | list) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CVClient 设备注册管理")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-activation", help="创建一次性激活码")
    create.add_argument("--tenant-id", required=True)
    create.add_argument("--label", default="")
    create.add_argument(
        "--ttl-hours", type=int, default=DEVICE_ACTIVATION_DEFAULT_TTL_HOURS
    )
    create.add_argument("--created-by", default="cli")

    list_devices = subparsers.add_parser("list-devices", help="列出注册设备")
    list_devices.add_argument("--tenant-id", default="")

    list_codes = subparsers.add_parser("list-activations", help="列出激活记录")
    list_codes.add_argument("--tenant-id", default="")
    list_codes.add_argument("--limit", type=int, default=100)

    revoke = subparsers.add_parser("revoke-device", help="撤销设备")
    revoke.add_argument("--device-id", required=True)

    activate = subparsers.add_parser("activate-device", help="重新启用设备")
    activate.add_argument("--device-id", required=True)

    purge = subparsers.add_parser(
        "purge-tenant-devices", help="清理租户设备控制面数据（不删除业务数据）"
    )
    purge.add_argument("--tenant-id", required=True)
    purge.add_argument(
        "--confirm",
        required=True,
        help="必须再次输入完全相同的 tenant_id",
    )
    return parser


def _purge_tenant_sessions(tenant_id: str) -> int:
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
            except json.JSONDecodeError:
                continue
            if normalize_tenant_id(str(payload.get("tenant_id") or "")) == tenant_id:
                deleted += int(client.delete(key) or 0)
    return deleted


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_parser().parse_args()
    repository = DeviceIdentityRepository()
    if args.command == "create-activation":
        raw_code, summary = repository.create_activation_code(
            args.tenant_id,
            label=args.label,
            ttl_seconds=max(1, args.ttl_hours) * 3600,
            created_by=args.created_by,
        )
        _print({"activationCode": raw_code, **asdict(summary)})
        return 0
    if args.command == "list-devices":
        devices = repository.list_devices(args.tenant_id or None)
        _print(
            [
                {
                    "deviceId": item.device_id,
                    "tenantId": item.tenant_id,
                    "installationId": item.installation_id,
                    "displayName": item.display_name,
                    "status": item.status,
                    "authVersion": item.auth_version,
                    "createdAt": item.created_at,
                    "lastSeenAt": item.last_seen_at,
                }
                for item in devices
            ]
        )
        return 0
    if args.command == "list-activations":
        values = repository.list_activation_codes(args.tenant_id or None, args.limit)
        _print([asdict(item) for item in values])
        return 0
    if args.command in {"revoke-device", "activate-device"}:
        status = "revoked" if args.command == "revoke-device" else "active"
        changed = repository.set_device_status(args.device_id, status)
        _print({"ok": changed, "deviceId": args.device_id, "status": status})
        return 0 if changed else 1
    if args.command == "purge-tenant-devices":
        tenant_id = normalize_tenant_id(args.tenant_id)
        if args.confirm != args.tenant_id or tenant_id != normalize_tenant_id(
            args.confirm
        ):
            raise SystemExit("--confirm 必须与 --tenant-id 完全一致")
        activations, devices = repository.purge_tenant_devices(tenant_id)
        sessions = _purge_tenant_sessions(tenant_id)
        _print(
            {
                "ok": True,
                "tenantId": tenant_id,
                "activationCodesDeleted": activations,
                "devicesDeleted": devices,
                "redisSessionsDeleted": sessions,
            }
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
