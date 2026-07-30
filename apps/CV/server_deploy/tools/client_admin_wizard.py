"""Guided tenant client provisioning and device administration."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEVICE_ACTIVATION_DEFAULT_TTL_HOURS
from core.client_admin import ClientAdminService


logger = logging.getLogger(__name__)


class ClientAdminWizard:
    def __init__(self, service: ClientAdminService) -> None:
        self.service = service

    def run(self) -> int:
        print("CVClient 客户端与设备管理向导")
        while True:
            print(
                "\n请选择操作：\n"
                "  1. 新建客户端（控制台密码 + 设备激活码）\n"
                "  2. 生成设备激活码\n"
                "  3. 重置控制台密码\n"
                "  4. 查看租户设备\n"
                "  5. 停用设备\n"
                "  6. 启用设备\n"
                "  7. 删除客户端控制面数据\n"
                "  8. 查看租户控制台管理员\n"
                "  0. 退出"
            )
            try:
                choice = input("输入序号：").strip()
            except EOFError:
                print("\n输入结束，已退出。")
                return 0
            if choice == "0":
                print("已退出。")
                return 0
            try:
                self._dispatch(choice)
            except KeyboardInterrupt:
                print("\n已取消当前操作。")
            except EOFError:
                print("\n输入结束，已退出。")
                return 0
            except Exception as exc:  # noqa: BLE001 - CLI should show concise errors.
                logger.exception("client admin wizard action failed")
                print(f"\n操作失败：{type(exc).__name__}: {exc}")

    def _dispatch(self, choice: str) -> None:
        actions = {
            "1": self._create_client,
            "2": self._create_activation,
            "3": self._reset_console_password,
            "4": self._list_devices,
            "5": lambda: self._set_device_status("revoked"),
            "6": lambda: self._set_device_status("active"),
            "7": self._delete_client,
            "8": self._list_console_admins,
        }
        action = actions.get(choice)
        if action is None:
            print("无效序号，请重新选择。")
            return
        action()

    def _create_client(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        tenant_name = _prompt("客户/租户名称", default=tenant_id)
        username = _prompt("控制台管理员用户名", default="admin")
        display_name = _prompt("控制台显示名", default="企业管理员")
        default_label = f"{tenant_name}前台"
        device_label = _prompt("设备激活码标签", default=default_label)
        ttl_hours = _prompt_int(
            "激活码有效期（小时）",
            default=DEVICE_ACTIVATION_DEFAULT_TTL_HOURS,
            minimum=1,
        )
        reset_existing = False
        if self.service.tenant_admins.get_account(tenant_id, username):
            reset_existing = _prompt_yes_no(
                "该控制台管理员已存在，是否同时重置密码？",
                default=False,
            )
        result = self.service.create_client(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            username=username,
            display_name=display_name,
            device_label=device_label,
            ttl_hours=ttl_hours,
            reset_existing_password=reset_existing,
            created_by="client-admin-wizard",
        )
        _print_payload(result)

    def _create_activation(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        label = _prompt("激活码标签", default=f"{tenant_id}前台")
        ttl_hours = _prompt_int(
            "激活码有效期（小时）",
            default=DEVICE_ACTIVATION_DEFAULT_TTL_HOURS,
            minimum=1,
        )
        result = self.service.create_activation(
            tenant_id=tenant_id,
            label=label,
            ttl_hours=ttl_hours,
        )
        _print_payload(result)

    def _reset_console_password(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        username = _prompt("控制台管理员用户名", default="admin")
        result = self.service.reset_console_password(
            tenant_id=tenant_id,
            username=username,
        )
        _print_payload(result)

    def _list_devices(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        _print_payload(self.service.list_devices(tenant_id))

    def _set_device_status(self, status: str) -> None:
        device_id = _prompt_required("设备 ID")
        action = "停用" if status == "revoked" else "启用"
        if not _prompt_yes_no(f"确认{action}设备 {device_id}？", default=False):
            print("已取消。")
            return
        _print_payload(self.service.set_device_status(device_id=device_id, status=status))

    def _delete_client(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        print("\n危险操作：将删除该租户的激活码、注册设备和设备会话。")
        print("不会删除员工、考勤、人脸向量、知识库或人物记忆。")
        confirm = input(f"请输入完整 tenant_id [{tenant_id}] 以确认：").strip()
        if confirm != tenant_id:
            print("确认值不匹配，已取消。")
            return
        disable_admins = _prompt_yes_no(
            "是否同时停用该租户控制台管理员？",
            default=True,
        )
        result = self.service.delete_client_control_plane(
            tenant_id=tenant_id,
            disable_console_admins=disable_admins,
        )
        _print_payload(result)

    def _list_console_admins(self) -> None:
        tenant_id = _prompt_required("租户 ID")
        _print_payload(self.service.list_console_admins(tenant_id))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="交互式管理 CVClient 客户端、控制台密码、激活码和设备"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="日志级别，默认 INFO",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return ClientAdminWizard(ClientAdminService()).run()


def _prompt(label: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}：").strip()
    return value or default


def _prompt_required(label: str) -> str:
    while True:
        value = input(f"{label}：").strip()
        if value:
            return value
        print(f"{label} 不能为空。")


def _prompt_int(label: str, *, default: int, minimum: int) -> int:
    while True:
        raw = _prompt(label, default=str(default))
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if value < minimum:
            print(f"不能小于 {minimum}。")
            continue
        return value


def _prompt_yes_no(label: str, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{hint}]：").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n。")

def _print_payload(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
