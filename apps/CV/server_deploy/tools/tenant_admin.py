"""Manage tenant-scoped control-console administrator accounts."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tenant_admin.passwords import hash_password
from core.tenant_admin.repository import TenantAdminRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="租户控制台管理员账号管理")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="创建租户管理员并生成初始密码")
    create.add_argument("--tenant-id", required=True)
    create.add_argument("--tenant-name", required=True)
    create.add_argument("--username", default="admin")
    create.add_argument("--display-name", default="企业管理员")

    reset = commands.add_parser("reset-password", help="重置管理员密码")
    reset.add_argument("--tenant-id", required=True)
    reset.add_argument("--username", default="admin")

    listing = commands.add_parser("list", help="列出管理员账号")
    listing.add_argument("--tenant-id", default="")

    for command, help_text in (
        ("disable", "停用管理员并使现有会话失效"),
        ("enable", "重新启用管理员"),
    ):
        item = commands.add_parser(command, help=help_text)
        item.add_argument("--tenant-id", required=True)
        item.add_argument("--username", default="admin")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repository = TenantAdminRepository()
    if args.command == "create":
        password = _new_password()
        try:
            account = repository.create_account(
                tenant_id=args.tenant_id,
                tenant_name=args.tenant_name,
                username=args.username,
                display_name=args.display_name,
                password_hash=hash_password(password),
            )
        except Exception as exc:
            raise SystemExit(f"创建失败；账号可能已存在: {exc}") from exc
        _print(
            {
                "ok": True,
                "tenantId": account.tenant_id,
                "tenantName": account.tenant_name,
                "username": account.username,
                "displayName": account.display_name,
                "initialPassword": password,
                "notice": "密码只在本次输出中显示，请立即安全交付给客户",
            }
        )
        return 0
    if args.command == "reset-password":
        password = _new_password()
        changed = repository.update_password(
            args.tenant_id,
            args.username,
            hash_password(password),
        )
        _print(
            {
                "ok": changed,
                "tenantId": args.tenant_id,
                "username": args.username,
                "newPassword": password if changed else "",
                "sessionsInvalidated": changed,
            }
        )
        return 0 if changed else 1
    if args.command == "list":
        _print(
            [
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
                for item in repository.list_accounts(args.tenant_id or None)
            ]
        )
        return 0
    status = "disabled" if args.command == "disable" else "active"
    changed = repository.set_status(args.tenant_id, args.username, status)
    _print(
        {
            "ok": changed,
            "tenantId": args.tenant_id,
            "username": args.username,
            "status": status,
            "sessionsInvalidated": changed,
        }
    )
    return 0 if changed else 1


def _new_password() -> str:
    return secrets.token_urlsafe(18)


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
