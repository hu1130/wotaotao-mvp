"""Tenant administrator accounts, sessions, and managed document settings."""

import os

from .common import get_int


TENANT_ADMIN_SESSION_TTL_SECONDS = get_int(
    "TENANT_ADMIN_SESSION_TTL_SECONDS", 43200
)
TENANT_ADMIN_SESSION_CACHE_SECONDS = get_int(
    "TENANT_ADMIN_SESSION_CACHE_SECONDS", 30
)
TENANT_ADMIN_DOCUMENT_MAX_BYTES = get_int(
    "TENANT_ADMIN_DOCUMENT_MAX_BYTES", 25 * 1024 * 1024
)
CONTROL_USERNAME = os.getenv("CONTROL_USERNAME", "admin").strip()
CONTROL_PASSWORD = os.getenv("CONTROL_PASSWORD", "").strip()
CONTROL_DEFAULT_TENANT_NAME = os.getenv(
    "CONTROL_DEFAULT_TENANT_NAME", "默认企业"
).strip()
