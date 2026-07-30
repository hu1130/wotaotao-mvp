"""FastAPI authentication dependencies shared by modular routers."""

from __future__ import annotations

import logging

from fastapi import Cookie, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from api.auth import (
    TenantContext,
    context_allows_request,
    get_tenant_credential_registry,
)
from config import API_SIGNATURE_TOLERANCE_SECONDS
from core.device_identity.service import (
    DeviceAuthenticationUnavailable,
    get_device_authentication_service,
)
from core.device_identity.sessions import get_device_session_store
from core.tenant_admin.sessions import get_tenant_admin_session_store


logger = logging.getLogger("uvicorn.error")


async def require_api_signature(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None),
    x_device_nonce: str | None = Header(default=None),
    x_device_timestamp: str | None = Header(default=None),
    x_device_signature: str | None = Header(default=None),
    x_avatar_session: str | None = Header(default=None),
    x_tenant_admin_session: str | None = Header(default=None),
    cv_control_session: str | None = Cookie(default=None),
) -> TenantContext:
    body = request.scope.get("raw_body")
    if body is None:
        body = await request.body()

    context = get_tenant_credential_registry().authenticate(
        method=request.method,
        path=request.url.path,
        timestamp=x_timestamp,
        body=body,
        api_key=x_api_key,
        signature=x_signature,
        tolerance_seconds=API_SIGNATURE_TOLERANCE_SECONDS,
    )
    try:
        if context is None and x_device_id:
            raw_query = request.scope.get("query_string") or b""
            signing_target = request.url.path
            if raw_query:
                signing_target += "?" + raw_query.decode("ascii", errors="strict")
            device = await run_in_threadpool(
                lambda: get_device_authentication_service().authenticate(
                    method=request.method,
                    path=signing_target,
                    timestamp=x_device_timestamp,
                    nonce=x_device_nonce,
                    device_id=x_device_id,
                    signature=x_device_signature,
                    body=body,
                    tolerance_seconds=API_SIGNATURE_TOLERANCE_SECONDS,
                )
            )
            if device is not None:
                context = TenantContext(
                    tenant_id=device.tenant_id,
                    credential_source="registered-device",
                    auth_method="device",
                    principal_id=device.device_id,
                    device_id=device.device_id,
                )
        if context is None and x_avatar_session:
            binding = await run_in_threadpool(
                get_device_session_store().authenticate_session,
                x_avatar_session,
            )
            if binding is not None:
                context = TenantContext(
                    tenant_id=binding.tenant_id,
                    credential_source="avatar-session",
                    auth_method="avatar-session",
                    principal_id=binding.device_id,
                    device_id=binding.device_id,
                )
        admin_session = x_tenant_admin_session or cv_control_session
        if context is None and admin_session:
            binding = await run_in_threadpool(
                get_tenant_admin_session_store().authenticate,
                admin_session,
            )
            if binding is not None:
                request.state.tenant_admin_session = binding
                context = TenantContext(
                    tenant_id=binding.tenant_id,
                    credential_source="tenant-admin-session",
                    auth_method="tenant-admin",
                    principal_id=str(binding.account_id),
                    principal_name=binding.display_name or binding.username,
                    tenant_name=binding.tenant_name,
                )
    except DeviceAuthenticationUnavailable as exc:
        logger.error("设备认证依赖不可用: path=%s error=%s", request.url.path, exc)
        raise HTTPException(
            status_code=503, detail="device authentication unavailable"
        ) from exc

    if context is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not context_allows_request(context, request.method, request.url.path):
        logger.warning(
            "认证主体越权请求已拒绝: auth=%s principal=%s method=%s path=%s",
            context.auth_method,
            context.principal_id,
            request.method,
            request.url.path,
        )
        raise HTTPException(
            status_code=403, detail="principal is not allowed for this endpoint"
        )
    request.state.tenant_context = context
    return context


def tenant_context_from_request(request: Request) -> TenantContext:
    context = getattr(request.state, "tenant_context", None)
    if not isinstance(context, TenantContext):
        raise HTTPException(status_code=401, detail="tenant authentication required")
    return context
