"""Public enrollment and tenant-bound avatar bootstrap endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from api.dependencies import require_api_signature, tenant_context_from_request
from api.schemas import (
    AvatarBootstrapConsumeRequest,
    AvatarBootstrapRequest,
    DeviceEnrollmentClaimRequest,
)
from config import DEVICE_ENROLLMENT_ENABLED
from core.device_identity.models import DeviceEnrollmentError
from core.device_identity.service import (
    DeviceAuthenticationUnavailable,
    get_device_authentication_service,
)
from core.device_identity.sessions import get_device_session_store


logger = logging.getLogger("uvicorn.error")
router = APIRouter()


@router.post("/api/v1/device-enrollment/claim")
async def claim_device(request: Request, payload: DeviceEnrollmentClaimRequest) -> dict:
    if not DEVICE_ENROLLMENT_ENABLED:
        raise HTTPException(status_code=404, detail="device enrollment is disabled")
    client_host = request.client.host if request.client else "unknown"
    try:
        result = await run_in_threadpool(
            lambda: get_device_authentication_service().enroll(
                activation_code=payload.activation_code,
                installation_id=payload.installation_id,
                public_key_b64=payload.public_key,
                proof_signature_b64=payload.proof_signature,
                display_name=payload.device_name,
                platform_info=payload.platform_info,
            )
        )
        bootstrap_token, bootstrap_expires_at = await run_in_threadpool(
            get_device_session_store().issue_bootstrap,
            result.device.tenant_id,
            result.device.device_id,
        )
    except DeviceEnrollmentError as exc:
        logger.warning(
            "设备激活失败: client=%s code=%s installation=%s",
            client_host,
            exc.code,
            payload.installation_id,
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except DeviceAuthenticationUnavailable as exc:
        logger.error("设备激活依赖不可用: client=%s error=%s", client_host, exc)
        raise HTTPException(
            status_code=503, detail="device enrollment unavailable"
        ) from exc

    logger.info(
        "设备激活接口完成: client=%s tenant=%s device=%s idempotent=%s",
        client_host,
        result.device.tenant_id,
        result.device.device_id,
        result.idempotent,
    )
    return {
        "ok": True,
        "data": {
            "tenantId": result.device.tenant_id,
            "deviceId": result.device.device_id,
            "idempotent": result.idempotent,
            "avatarBootstrapToken": bootstrap_token,
            "avatarBootstrapExpiresAt": bootstrap_expires_at,
        },
    }


@router.post(
    "/api/v1/device-sessions/avatar-bootstrap",
    dependencies=[Depends(require_api_signature)],
)
async def create_avatar_bootstrap(
    request: Request, payload: AvatarBootstrapRequest
) -> dict:
    context = tenant_context_from_request(request)
    device_id = (
        context.device_id if context.auth_method == "device" else payload.device_id
    )
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    try:
        token, expires_at = await run_in_threadpool(
            get_device_session_store().issue_bootstrap,
            context.tenant_id,
            device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DeviceAuthenticationUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="device session unavailable"
        ) from exc
    return {
        "ok": True,
        "data": {
            "token": token,
            "tenantId": context.tenant_id,
            "deviceId": device_id,
            "expiresAt": expires_at,
        },
    }


@router.post(
    "/api/v1/device-sessions/avatar-state-session",
    dependencies=[Depends(require_api_signature)],
)
async def create_avatar_state_session(request: Request) -> dict:
    """Issue a short-lived Node state credential to the authenticated device."""

    context = tenant_context_from_request(request)
    if context.auth_method != "device" or not context.device_id:
        raise HTTPException(
            status_code=403,
            detail="device authentication is required",
        )
    try:
        token, binding = await run_in_threadpool(
            get_device_session_store().issue_session,
            context.tenant_id,
            context.device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DeviceAuthenticationUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="device session unavailable"
        ) from exc
    logger.info(
        "数字人状态会话已签发: tenant=%s device=%s",
        binding.tenant_id,
        binding.device_id,
    )
    return {
        "ok": True,
        "data": {
            "sessionToken": token,
            "tenantId": binding.tenant_id,
            "deviceId": binding.device_id,
            "expiresAt": binding.expires_at,
        },
    }


@router.post("/api/v1/device-sessions/avatar-bootstrap/consume")
async def consume_avatar_bootstrap(payload: AvatarBootstrapConsumeRequest) -> dict:
    try:
        result = await run_in_threadpool(
            get_device_session_store().consume_bootstrap,
            payload.token,
        )
    except DeviceAuthenticationUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="device session unavailable"
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=401, detail="invalid or expired bootstrap token"
        )
    token, binding = result
    return {
        "ok": True,
        "data": {
            "sessionToken": token,
            "tenantId": binding.tenant_id,
            "deviceId": binding.device_id,
            "expiresAt": binding.expires_at,
        },
    }


@router.get(
    "/api/v1/device-sessions/avatar-session",
    dependencies=[Depends(require_api_signature)],
)
async def avatar_session_status(request: Request) -> dict:
    context = tenant_context_from_request(request)
    return {
        "ok": True,
        "data": {
            "tenantId": context.tenant_id,
            "deviceId": context.device_id,
            "authMethod": context.auth_method,
        },
    }
