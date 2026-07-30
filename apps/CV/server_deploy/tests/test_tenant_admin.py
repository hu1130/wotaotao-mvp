from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import Request

from api.auth import TenantContext, context_allows_request
from api.dependencies import require_api_signature
from api.tenant_admin import _require_platform_admin
from core.tenant_admin.documents import TenantKnowledgeDocumentService
from core.tenant_admin.models import TenantAdminAccount, TenantAdminSessionBinding
from core.tenant_admin.passwords import hash_password, verify_password
from core.tenant_admin.service import TenantAdminAuthenticationService
from core.tenant_admin.sessions import TenantAdminSessionStore


class FakeRepository:
    def __init__(self, account: TenantAdminAccount | None = None) -> None:
        self.account = account
        self.logins: list[int] = []

    def get_account(self, tenant_id: str, username: str):
        if self.account is None:
            return None
        if (tenant_id, username.casefold()) == (
            self.account.tenant_id,
            self.account.username,
        ):
            return self.account
        return None

    def get_account_by_id(self, account_id: int):
        if self.account and account_id == self.account.account_id:
            return self.account
        return None

    def record_login(self, account_id: int) -> None:
        self.logins.append(account_id)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def get(self, key: str):
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeHealth:
    def __init__(self) -> None:
        self.client = FakeRedis()

    def ensure_connected(self) -> bool:
        return True

    def mark_unhealthy(self) -> None:
        raise AssertionError("fake Redis should stay healthy")


def build_account(**changes) -> TenantAdminAccount:
    account = TenantAdminAccount(
        account_id=7,
        tenant_id="tenant-a",
        tenant_name="A 企业",
        username="admin",
        display_name="企业管理员",
        password_hash=hash_password("correct-password-123"),
        status="active",
        auth_version=3,
    )
    return replace(account, **changes)


class TenantAdminTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verified(self) -> None:
        first = hash_password("correct-password-123")
        second = hash_password("correct-password-123")

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct-password-123", first))
        self.assertFalse(verify_password("wrong-password", first))
        with self.assertRaisesRegex(ValueError, "12"):
            hash_password("too-short")

    def test_legacy_bootstrap_can_hash_existing_short_password(self) -> None:
        encoded = hash_password("legacy", enforce_policy=False)

        self.assertTrue(verify_password("legacy", encoded))

    def test_authentication_checks_tenant_status_and_password(self) -> None:
        repository = FakeRepository(build_account())
        service = TenantAdminAuthenticationService(repository)

        authenticated = service.authenticate(
            "tenant-a", "admin", "correct-password-123"
        )

        self.assertEqual(authenticated.account_id, 7)
        self.assertEqual(repository.logins, [7])
        self.assertIsNone(
            service.authenticate("tenant-b", "admin", "correct-password-123")
        )
        repository.account = replace(repository.account, status="disabled")
        self.assertIsNone(
            service.authenticate("tenant-a", "admin", "correct-password-123")
        )

    def test_redis_session_is_tenant_bound_and_auth_version_revokes_it(self) -> None:
        repository = FakeRepository(build_account())
        health = FakeHealth()
        store = TenantAdminSessionStore(health, repository)

        token, issued = store.issue(repository.account)
        authenticated = store.authenticate(token)

        self.assertEqual(issued.tenant_id, "tenant-a")
        self.assertEqual(authenticated.tenant_id, "tenant-a")
        repository.account = replace(repository.account, auth_version=4)
        self.assertIsNone(store.authenticate(token))

    def test_managed_documents_stay_inside_tenant_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "core.tenant_admin.documents.KNOWLEDGE_BASE_DIR", temp_dir
            ):
                service = TenantKnowledgeDocumentService("tenant-a")
                saved = service.save("../company.md", io.BytesIO("企业资料".encode()))

                self.assertEqual(saved["relativePath"], "company.md")
                self.assertEqual(len(service.list_documents()), 1)
                self.assertTrue(
                    str(service.root).startswith(
                        str(Path(temp_dir).resolve() / "tenants" / "tenant-a")
                    )
                )
                with self.assertRaisesRegex(ValueError, "路径"):
                    service.delete("../../tenant-b/private.md")
                self.assertTrue(service.delete("company.md"))

    def test_tenant_admin_is_allowed_only_inside_v1_api_namespace(self) -> None:
        context = TenantContext("tenant-a", auth_method="tenant-admin")

        self.assertTrue(
            context_allows_request(context, "DELETE", "/api/v1/employees/alice")
        )
        self.assertFalse(context_allows_request(context, "GET", "/internal/debug"))

    def test_platform_admin_requires_default_platform_tenant(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/platform-admin/clients",
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("test", 80),
                "client": ("test", 1234),
            }
        )
        request.state.tenant_context = TenantContext(
            "default",
            auth_method="tenant-admin",
            principal_id="1",
        )
        self.assertEqual(_require_platform_admin(request).tenant_id, "default")

        request.state.tenant_context = TenantContext(
            "tenant-a",
            auth_method="tenant-admin",
            principal_id="7",
        )
        with self.assertRaisesRegex(Exception, "platform administrator"):
            _require_platform_admin(request)


class TenantAdminDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_cookie_binding_is_saved_on_request_state(self) -> None:
        binding = TenantAdminSessionBinding(
            account_id=7,
            tenant_id="tenant-a",
            tenant_name="A 企业",
            username="admin",
            display_name="企业管理员",
            auth_version=3,
            expires_at=9999999999.0,
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/tenant-admin/session",
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("test", 80),
                "client": ("test", 1234),
                "raw_body": b"",
            }
        )
        with (
            patch("api.dependencies.get_tenant_credential_registry") as registry,
            patch("api.dependencies.get_tenant_admin_session_store") as store,
        ):
            registry.return_value.authenticate.return_value = None
            store.return_value.authenticate.return_value = binding
            context = await require_api_signature(
                request,
                x_api_key=None,
                x_timestamp=None,
                x_signature=None,
                x_device_id=None,
                x_device_nonce=None,
                x_device_timestamp=None,
                x_device_signature=None,
                x_avatar_session=None,
                x_tenant_admin_session=None,
                cv_control_session="admin-session-token",
            )

        self.assertEqual(context.auth_method, "tenant-admin")
        self.assertEqual(context.tenant_id, "tenant-a")
        self.assertEqual(request.state.tenant_admin_session, binding)


if __name__ == "__main__":
    unittest.main()
