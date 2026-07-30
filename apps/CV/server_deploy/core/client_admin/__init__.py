"""Platform client administration services."""

from .service import ClientAdminService, purge_device_sessions, purge_tenant_device_sessions

__all__ = [
    "ClientAdminService",
    "purge_device_sessions",
    "purge_tenant_device_sessions",
]
