from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

from core.client_admin.service import ClientAdminService
from core.device_identity.models import ActivationCodeSummary, DeviceRecord
from core.tenant_admin.models import TenantAdminAccount


@dataclass
class FakeTenantAdmins:
    accounts: list[TenantAdminAccount]
    disabled: list[tuple[str, str]]

    def list_accounts(self, tenant_id=None):
        if tenant_id is None:
            return list(self.accounts)
        return [item for item in self.accounts if item.tenant_id == tenant_id]

    def get_account(self, tenant_id, username):
        for account in self.accounts:
            if account.tenant_id == tenant_id and account.username == username:
                return account
        return None

    def create_account(self, **kwargs):
        account = TenantAdminAccount(
            account_id=len(self.accounts) + 1,
            tenant_id=kwargs["tenant_id"],
            tenant_name=kwargs["tenant_name"],
            username=kwargs["username"],
            display_name=kwargs["display_name"],
            password_hash=kwargs["password_hash"],
            status="active",
            auth_version=1,
            created_at=datetime(2026, 7, 20, 9, 0, 0),
        )
        self.accounts.append(account)
        return account

    def update_password(self, tenant_id, username, _password_hash):
        return self.get_account(tenant_id, username) is not None

    def set_status(self, tenant_id, username, status):
        self.disabled.append((tenant_id, username))
        return status == "disabled" and self.get_account(tenant_id, username) is not None


class FakeDevices:
    def __init__(self):
        now = datetime.now()
        self.devices = [
            DeviceRecord(
                device_id="dev_a",
                tenant_id="tenant-a",
                installation_id="11111111-1111-1111-1111-111111111111",
                public_key=b"1" * 32,
                display_name="A 前台",
                status="active",
                auth_version=1,
                created_at=now,
                last_seen_at=now,
            )
        ]
        self.activations = [
            ActivationCodeSummary(
                activation_id=1,
                tenant_id="tenant-a",
                code_prefix="act_secret1",
                label="A 前台",
                expires_at=now + timedelta(hours=1),
                claimed_at=None,
                claimed_device_id="",
                created_at=now,
                activation_code="act_secret1_full",
            )
        ]
        self.purged_tenant = ""

    def list_devices(self, tenant_id=None):
        if tenant_id is None:
            return list(self.devices)
        return [item for item in self.devices if item.tenant_id == tenant_id]

    def list_activation_codes(self, tenant_id=None, limit=100):
        if tenant_id is None:
            return list(self.activations)[:limit]
        return [item for item in self.activations if item.tenant_id == tenant_id][:limit]

    def create_activation_code(self, tenant_id, *, label, ttl_seconds, created_by):
        summary = ActivationCodeSummary(
            activation_id=2,
            tenant_id=tenant_id,
            code_prefix="act_secret2",
            label=label,
            expires_at=datetime(2026, 7, 21, 10, 0, 0),
            claimed_at=None,
            claimed_device_id="",
            created_at=datetime(2026, 7, 20, 10, 0, 0),
            activation_code="act_secret2_full",
        )
        self.activations.append(summary)
        return "act_secret2_full", summary

    def set_device_status(self, device_id, status):
        return device_id == "dev_a" and status in {"active", "revoked"}

    def delete_device(self, device_id):
        for index, device in enumerate(self.devices):
            if device.device_id == device_id:
                return self.devices.pop(index)
        return None

    def delete_activation_code(self, *, tenant_id, activation_id):
        for index, activation in enumerate(self.activations):
            if (
                activation.tenant_id == tenant_id
                and activation.activation_id == int(activation_id)
            ):
                return self.activations.pop(index)
        return None

    def purge_tenant_devices(self, tenant_id):
        self.purged_tenant = tenant_id
        return (1, 1)


class ClientAdminServiceTests(unittest.TestCase):
    def build_service(self):
        admins = FakeTenantAdmins(
            accounts=[
                TenantAdminAccount(
                    account_id=1,
                    tenant_id="tenant-a",
                    tenant_name="A 企业",
                    username="admin",
                    display_name="企业管理员",
                    password_hash="hash",
                    status="active",
                    auth_version=1,
                    created_at=datetime(2026, 7, 20, 8, 0, 0),
                )
            ],
            disabled=[],
        )
        devices = FakeDevices()
        return ClientAdminService(tenant_admins=admins, devices=devices), admins, devices

    def test_list_clients_aggregates_admins_devices_and_activations(self):
        service, _admins, _devices = self.build_service()

        clients = service.list_clients()

        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["tenantId"], "tenant-a")
        self.assertEqual(clients[0]["activeAdminCount"], 1)
        self.assertEqual(clients[0]["activeDeviceCount"], 1)
        self.assertEqual(clients[0]["availableActivationCount"], 1)

    def test_list_activations_exposes_only_unclaimed_activation_code(self):
        service, _admins, devices = self.build_service()
        now = datetime.now()
        devices.activations.append(
            ActivationCodeSummary(
                activation_id=3,
                tenant_id="tenant-a",
                code_prefix="act_claimed",
                label="已使用",
                expires_at=now + timedelta(hours=1),
                claimed_at=now,
                claimed_device_id="dev_a",
                created_at=now,
                activation_code="act_claimed_full",
            )
        )

        activations = service.list_activations("tenant-a")

        by_id = {item["activationId"]: item for item in activations}
        self.assertEqual(by_id[1]["activationCode"], "act_secret1_full")
        self.assertNotIn("activationCode", by_id[3])

    def test_list_clients_hides_deleted_control_plane_shell(self):
        service, admins, devices = self.build_service()
        admins.accounts.append(
            TenantAdminAccount(
                account_id=2,
                tenant_id="deleted-tenant",
                tenant_name="已删除客户",
                username="admin",
                display_name="企业管理员",
                password_hash="hash",
                status="disabled",
                auth_version=2,
                created_at=datetime.now(),
            )
        )

        clients = service.list_clients()

        self.assertEqual([item["tenantId"] for item in clients], ["tenant-a"])
        self.assertEqual(devices.purged_tenant, "")

    def test_delete_client_only_clears_control_plane(self):
        service, admins, devices = self.build_service()

        with patch("core.client_admin.service.purge_tenant_device_sessions", return_value=2):
            result = service.delete_client_control_plane(tenant_id="tenant-a")

        self.assertTrue(result["ok"])
        self.assertEqual(result["businessDataDeleted"], False)
        self.assertEqual(result["redisSessionsDeleted"], 2)
        self.assertEqual(devices.purged_tenant, "tenant-a")
        self.assertEqual(admins.disabled, [("tenant-a", "admin")])

    def test_delete_device_clears_device_sessions(self):
        service, _admins, _devices = self.build_service()

        with patch("core.client_admin.service.purge_device_sessions", return_value=3):
            result = service.delete_device(device_id="dev_a")

        self.assertTrue(result["deleted"])
        self.assertEqual(result["tenantId"], "tenant-a")
        self.assertEqual(result["redisSessionsDeleted"], 3)

    def test_delete_activation_requires_tenant_match(self):
        service, _admins, devices = self.build_service()

        missing = service.delete_activation(tenant_id="other-tenant", activation_id=1)
        deleted = service.delete_activation(tenant_id="tenant-a", activation_id=1)

        self.assertFalse(missing["deleted"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["activationId"], 1)
        self.assertEqual(devices.activations, [])


if __name__ == "__main__":
    unittest.main()
