from __future__ import annotations

import unittest

from api.auth import TenantContext, context_allows_request


class AuthPermissionTests(unittest.TestCase):
    def test_avatar_session_can_only_create_client_tasks(self) -> None:
        context = TenantContext(
            tenant_id="tenant-a",
            auth_method="avatar-session",
            principal_id="dev-a",
            device_id="dev-a",
        )

        self.assertTrue(
            context_allows_request(context, "POST", "/api/v1/client-tasks")
        )
        self.assertFalse(
            context_allows_request(context, "GET", "/api/v1/client-tasks/next")
        )
        self.assertFalse(
            context_allows_request(
                context, "POST", "/api/v1/client-tasks/task-1/complete"
            )
        )


if __name__ == "__main__":
    unittest.main()
