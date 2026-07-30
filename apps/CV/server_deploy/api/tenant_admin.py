"""Tenant-bound control-console authentication and management endpoints."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool

from api.dependencies import require_api_signature, tenant_context_from_request
from api.schemas import (
    PlatformActivationCreateRequest,
    PlatformClientCreateRequest,
    PlatformClientDeleteRequest,
    PlatformConsolePasswordResetRequest,
    PlatformDeviceDeleteRequest,
    TenantAdminLoginRequest,
    TenantAvatarPersonaRequest,
    TenantDeviceStatusRequest,
)
from config import RUNTIME_DEFAULT_TENANT_ID
from core.client_admin import ClientAdminService
from core.daily_tts_texts import delete_tenant_daily_texts, invalidate_tenant_daily_texts
from core.device_identity.repository import DeviceIdentityRepository
from core.device_identity.service import DeviceAuthenticationUnavailable
from core.tenant import normalize_tenant_id
from core.tenant_admin.documents import TenantKnowledgeDocumentService
from core.tenant_admin.service import get_tenant_admin_auth_service
from core.tenant_admin.sessions import get_tenant_admin_session_store
from core.tenant_avatar import get_tenant_avatar_persona_service
from tools.generate_daily_tts_texts import generate_tenant_daily_texts


logger = logging.getLogger("uvicorn.error")
router = APIRouter()
_avatar_quote_status_lock = threading.RLock()
_avatar_quote_statuses: dict[str, dict] = {}


@router.post(
    "/api/v1/tenant-admin/login",
    dependencies=[Depends(require_api_signature)],
)
async def login_tenant_admin(
    request: Request, payload: TenantAdminLoginRequest
) -> dict:
    caller = tenant_context_from_request(request)
    if caller.auth_method != "hmac" or caller.credential_source != "legacy-default":
        raise HTTPException(status_code=403, detail="server credential required")
    account = await run_in_threadpool(
        get_tenant_admin_auth_service().authenticate,
        payload.tenant_id,
        payload.username,
        payload.password,
    )
    if account is None:
        logger.warning(
            "租户管理员登录失败: tenant=%s username=%s",
            payload.tenant_id,
            payload.username,
        )
        raise HTTPException(status_code=401, detail="invalid tenant or credentials")
    try:
        token, binding = await run_in_threadpool(
            get_tenant_admin_session_store().issue,
            account,
        )
    except DeviceAuthenticationUnavailable as exc:
        raise HTTPException(status_code=503, detail="admin session unavailable") from exc
    return {
        "ok": True,
        "data": {"sessionToken": token, **_binding_payload(binding)},
    }


@router.get(
    "/api/v1/tenant-admin/session",
    dependencies=[Depends(require_api_signature)],
)
async def tenant_admin_session(request: Request) -> dict:
    _require_tenant_admin(request)
    binding = getattr(request.state, "tenant_admin_session", None)
    if binding is None:
        raise HTTPException(status_code=401, detail="tenant admin session missing")
    return {
        "ok": True,
        "data": {**_binding_payload(binding), "authMethod": "tenant-admin"},
    }


@router.post(
    "/api/v1/tenant-admin/logout",
    dependencies=[Depends(require_api_signature)],
)
async def logout_tenant_admin(
    request: Request,
    x_tenant_admin_session: str | None = Header(default=None),
) -> dict:
    _require_tenant_admin(request)
    token = x_tenant_admin_session or request.cookies.get("cv_control_session", "")
    if token:
        await run_in_threadpool(get_tenant_admin_session_store().revoke, token)
    return {"ok": True}


@router.get(
    "/api/v1/tenant-admin/devices",
    dependencies=[Depends(require_api_signature)],
)
async def list_tenant_devices(request: Request) -> dict:
    context = _require_tenant_admin(request)
    devices = await run_in_threadpool(
        DeviceIdentityRepository().list_devices,
        context.tenant_id,
    )
    return {
        "ok": True,
        "data": [
            {
                "deviceId": item.device_id,
                "displayName": item.display_name,
                "status": item.status,
                "createdAt": item.created_at,
                "lastSeenAt": item.last_seen_at,
            }
            for item in devices
        ],
    }


@router.post(
    "/api/v1/tenant-admin/devices/{device_id}/status",
    dependencies=[Depends(require_api_signature)],
)
async def set_tenant_device_status(
    request: Request,
    device_id: str,
    payload: TenantDeviceStatusRequest,
) -> dict:
    context = _require_tenant_admin(request)
    repository = DeviceIdentityRepository()
    device = await run_in_threadpool(repository.get_device, device_id)
    if device is None or device.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="device not found")
    changed = await run_in_threadpool(
        repository.set_device_status,
        device_id,
        payload.status,
    )
    return {
        "ok": True,
        "data": {"deviceId": device_id, "status": payload.status, "changed": changed},
    }


@router.get(
    "/api/v1/platform-admin/clients",
    dependencies=[Depends(require_api_signature)],
)
async def list_platform_clients(request: Request) -> dict:
    context = _require_platform_admin(request)
    data = await run_in_threadpool(ClientAdminService().list_clients)
    logger.info(
        "平台客户端列表已读取: principal=%s clients=%d",
        context.principal_id,
        len(data),
    )
    return {"ok": True, "data": data}


@router.post(
    "/api/v1/platform-admin/clients",
    dependencies=[Depends(require_api_signature)],
)
async def create_platform_client(
    request: Request,
    payload: PlatformClientCreateRequest,
) -> dict:
    context = _require_platform_admin(request)
    try:
        data = await run_in_threadpool(
            lambda: ClientAdminService().create_client(
                tenant_id=payload.tenant_id,
                tenant_name=payload.tenant_name or payload.tenant_id,
                username=payload.username,
                display_name=payload.display_name,
                device_label=(
                    payload.device_label
                    or f"{payload.tenant_name or payload.tenant_id}前台"
                ),
                ttl_hours=payload.ttl_hours,
                reset_existing_password=payload.reset_existing_password,
                created_by="platform-admin-page",
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.warning(
        "平台客户端创建接口完成: principal=%s tenant=%s username=%s",
        context.principal_id,
        data.get("tenantId"),
        (data.get("console") or {}).get("username"),
    )
    return {"ok": True, "data": data}


@router.delete(
    "/api/v1/platform-admin/clients/{tenant_id}",
    dependencies=[Depends(require_api_signature)],
)
async def delete_platform_client(
    request: Request,
    tenant_id: str,
    payload: PlatformClientDeleteRequest,
) -> dict:
    context = _require_platform_admin(request)
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    if normalize_tenant_id(payload.confirm_tenant_id) != normalized_tenant_id:
        raise HTTPException(status_code=400, detail="tenant confirmation mismatch")
    data = await run_in_threadpool(
        lambda: ClientAdminService().delete_client_control_plane(
            tenant_id=normalized_tenant_id,
            disable_console_admins=payload.disable_console_admins,
        )
    )
    logger.warning(
        "平台客户端控制面删除接口完成: principal=%s tenant=%s devices=%s activations=%s",
        context.principal_id,
        normalized_tenant_id,
        data.get("devicesDeleted"),
        data.get("activationCodesDeleted"),
    )
    return {"ok": True, "data": data}


@router.get(
    "/api/v1/platform-admin/clients/{tenant_id}/admins",
    dependencies=[Depends(require_api_signature)],
)
async def list_platform_client_admins(request: Request, tenant_id: str) -> dict:
    _require_platform_admin(request)
    data = await run_in_threadpool(
        lambda: ClientAdminService().list_console_admins(tenant_id)
    )
    return {"ok": True, "data": data}


@router.post(
    "/api/v1/platform-admin/clients/{tenant_id}/admins/password",
    dependencies=[Depends(require_api_signature)],
)
async def reset_platform_client_admin_password(
    request: Request,
    tenant_id: str,
    payload: PlatformConsolePasswordResetRequest,
) -> dict:
    context = _require_platform_admin(request)
    try:
        data = await run_in_threadpool(
            lambda: ClientAdminService().reset_console_password(
                tenant_id=tenant_id,
                username=payload.username,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail="tenant admin account not found")
    logger.warning(
        "平台客户端管理员密码重置接口完成: principal=%s tenant=%s username=%s",
        context.principal_id,
        data.get("tenantId"),
        data.get("username"),
    )
    return {"ok": True, "data": data}


@router.get(
    "/api/v1/platform-admin/clients/{tenant_id}/activations",
    dependencies=[Depends(require_api_signature)],
)
async def list_platform_client_activations(request: Request, tenant_id: str) -> dict:
    _require_platform_admin(request)
    data = await run_in_threadpool(
        lambda: ClientAdminService().list_activations(tenant_id)
    )
    return {"ok": True, "data": data}


@router.post(
    "/api/v1/platform-admin/clients/{tenant_id}/activations",
    dependencies=[Depends(require_api_signature)],
)
async def create_platform_client_activation(
    request: Request,
    tenant_id: str,
    payload: PlatformActivationCreateRequest,
) -> dict:
    context = _require_platform_admin(request)
    data = await run_in_threadpool(
        lambda: ClientAdminService().create_activation(
            tenant_id=tenant_id,
            label=payload.label or f"{normalize_tenant_id(tenant_id)}前台",
            ttl_hours=payload.ttl_hours,
            created_by="platform-admin-page",
        )
    )
    logger.warning(
        "平台客户端激活码已新增: principal=%s tenant=%s prefix=%s",
        context.principal_id,
        data.get("tenantId"),
        data.get("codePrefix"),
    )
    return {"ok": True, "data": data}


@router.delete(
    "/api/v1/platform-admin/clients/{tenant_id}/activations/{activation_id}",
    dependencies=[Depends(require_api_signature)],
)
async def delete_platform_client_activation(
    request: Request,
    tenant_id: str,
    activation_id: int,
) -> dict:
    context = _require_platform_admin(request)
    data = await run_in_threadpool(
        lambda: ClientAdminService().delete_activation(
            tenant_id=tenant_id,
            activation_id=activation_id,
        )
    )
    if not data.get("deleted"):
        raise HTTPException(status_code=404, detail="activation code not found")
    logger.warning(
        "平台客户端激活码已删除: principal=%s tenant=%s activation_id=%s prefix=%s",
        context.principal_id,
        data.get("tenantId"),
        data.get("activationId"),
        data.get("codePrefix"),
    )
    return {"ok": True, "data": data}


@router.get(
    "/api/v1/platform-admin/clients/{tenant_id}/devices",
    dependencies=[Depends(require_api_signature)],
)
async def list_platform_client_devices(request: Request, tenant_id: str) -> dict:
    _require_platform_admin(request)
    data = await run_in_threadpool(lambda: ClientAdminService().list_devices(tenant_id))
    return {"ok": True, "data": data}


@router.post(
    "/api/v1/platform-admin/devices/{device_id}/status",
    dependencies=[Depends(require_api_signature)],
)
async def set_platform_device_status(
    request: Request,
    device_id: str,
    payload: TenantDeviceStatusRequest,
) -> dict:
    _require_platform_admin(request)
    data = await run_in_threadpool(
        lambda: ClientAdminService().set_device_status(
            device_id=device_id,
            status=payload.status,
        )
    )
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail="device not found")
    return {"ok": True, "data": data}


@router.delete(
    "/api/v1/platform-admin/devices/{device_id}",
    dependencies=[Depends(require_api_signature)],
)
async def delete_platform_device(
    request: Request,
    device_id: str,
    payload: PlatformDeviceDeleteRequest,
) -> dict:
    context = _require_platform_admin(request)
    if payload.confirm_device_id != device_id:
        raise HTTPException(status_code=400, detail="device confirmation mismatch")
    data = await run_in_threadpool(
        lambda: ClientAdminService().delete_device(device_id=device_id)
    )
    if not data.get("deleted"):
        raise HTTPException(status_code=404, detail="device not found")
    logger.warning(
        "平台注册设备删除接口完成: principal=%s tenant=%s device=%s",
        context.principal_id,
        data.get("tenantId"),
        data.get("deviceId"),
    )
    return {"ok": True, "data": data}


@router.get(
    "/api/v1/tenant-admin/avatar-persona",
    dependencies=[Depends(require_api_signature)],
)
async def get_avatar_persona(request: Request) -> dict:
    context = _require_tenant_admin(request)
    settings = await run_in_threadpool(
        get_tenant_avatar_persona_service().resolve,
        context.tenant_id,
    )
    return {"ok": True, "data": settings.to_public_dict()}


@router.put(
    "/api/v1/tenant-admin/avatar-persona",
    dependencies=[Depends(require_api_signature)],
)
async def update_avatar_persona(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: TenantAvatarPersonaRequest,
) -> dict:
    context = _require_tenant_admin(request)
    service = get_tenant_avatar_persona_service()
    saved = await run_in_threadpool(
        service.save,
        tenant_id=context.tenant_id,
        assistant_name=payload.assistant_name,
        personality=payload.personality,
        speaking_tone=payload.speaking_tone,
        extra_instructions=payload.extra_instructions,
        wake_aliases=payload.wake_aliases,
    )
    settings = await run_in_threadpool(service.resolve, context.tenant_id)
    quote_generation = _schedule_tenant_avatar_quotes(
        context.tenant_id,
        settings,
        background_tasks,
    )
    logger.info(
        "租户数字人人设接口已保存: tenant=%s version=%s quote_status=%s",
        context.tenant_id,
        saved.version,
        quote_generation.get("status"),
    )
    return {
        "ok": True,
        "data": {**settings.to_public_dict(), "quoteGeneration": quote_generation},
    }


@router.get(
    "/api/v1/tenant-admin/avatar-persona/quote-status",
    dependencies=[Depends(require_api_signature)],
)
async def get_avatar_persona_quote_status(request: Request) -> dict:
    context = _require_tenant_admin(request)
    return {"ok": True, "data": _get_avatar_quote_status(context.tenant_id)}


@router.get(
    "/api/v1/tenant-admin/knowledge-documents",
    dependencies=[Depends(require_api_signature)],
)
async def list_knowledge_documents(request: Request) -> dict:
    context = _require_tenant_admin(request)
    documents = await run_in_threadpool(
        TenantKnowledgeDocumentService(context.tenant_id).list_documents
    )
    return {"ok": True, "data": documents}


@router.post(
    "/api/v1/tenant-admin/knowledge-documents",
    dependencies=[Depends(require_api_signature)],
)
async def upload_knowledge_documents(
    request: Request,
    files: list[UploadFile] = File(...),
) -> dict:
    context = _require_tenant_admin(request)
    service = TenantKnowledgeDocumentService(context.tenant_id)
    uploaded = []
    try:
        for item in files:
            uploaded.append(
                await run_in_threadpool(
                    service.save,
                    item.filename or "",
                    item.file,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        for item in files:
            await item.close()
    logger.info(
        "租户企业文档已上传: tenant=%s files=%d",
        context.tenant_id,
        len(uploaded),
    )
    return {"ok": True, "data": uploaded}


@router.delete(
    "/api/v1/tenant-admin/knowledge-documents/{relative_path:path}",
    dependencies=[Depends(require_api_signature)],
)
async def delete_knowledge_document(request: Request, relative_path: str) -> dict:
    context = _require_tenant_admin(request)
    try:
        deleted = await run_in_threadpool(
            TenantKnowledgeDocumentService(context.tenant_id).delete,
            relative_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
    logger.warning(
        "租户企业文档已删除: tenant=%s path=%s",
        context.tenant_id,
        relative_path,
    )
    return {"ok": True, "data": {"relativePath": relative_path, "deleted": True}}


def _require_tenant_admin(request: Request):
    context = tenant_context_from_request(request)
    if context.auth_method != "tenant-admin":
        raise HTTPException(status_code=403, detail="tenant administrator required")
    return context


def _refresh_tenant_avatar_quotes(tenant_id: str, settings) -> dict:
    tenant_id = normalize_tenant_id(tenant_id)
    if not getattr(settings, "customized", False):
        deleted = delete_tenant_daily_texts(tenant_id)
        logger.info(
            "租户数字人语录已恢复默认: tenant=%s deleted_custom=%s version=%s",
            tenant_id,
            deleted,
            getattr(settings, "version", 0),
        )
        return {
            "ok": True,
            "status": "default",
            "message": "已恢复默认人设，继续使用默认语录",
            "deletedCustomQuotes": deleted,
            "version": getattr(settings, "version", 0),
        }

    try:
        output_path = generate_tenant_daily_texts(
            tenant_id=tenant_id,
            persona_settings=settings,
            allow_fallback=False,
        )
        invalidate_tenant_daily_texts(tenant_id)
        logger.info(
            "租户数字人人设语录已生成: tenant=%s version=%s path=%s",
            tenant_id,
            getattr(settings, "version", 0),
            output_path,
        )
        return {
            "ok": True,
            "status": "generated",
            "message": "新语录生成成功",
            "version": getattr(settings, "version", 0),
        }
    except Exception as exc:
        logger.warning(
            "租户数字人人设语录生成失败: tenant=%s version=%s error=%s",
            tenant_id,
            getattr(settings, "version", 0),
            exc,
        )
        return {
            "ok": False,
            "status": "failed",
            "message": "新人设已保存，但新语录生成失败",
            "error": str(exc),
            "version": getattr(settings, "version", 0),
        }


def _schedule_tenant_avatar_quotes(
    tenant_id: str,
    settings,
    background_tasks: BackgroundTasks,
) -> dict:
    tenant_id = normalize_tenant_id(tenant_id)
    generation_id = f"{tenant_id}:{getattr(settings, 'version', 0)}:{time.time_ns()}"
    if not getattr(settings, "customized", False):
        result = _refresh_tenant_avatar_quotes(tenant_id, settings)
        return _set_avatar_quote_status(
            tenant_id,
            generation_id=generation_id,
            running=False,
            complete=True,
            status=result.get("status", "default"),
            message=result.get("message", "已恢复默认人设，继续使用默认语录"),
            error=result.get("error", ""),
            version=getattr(settings, "version", 0),
            finished_at=_now_iso(),
        )

    status = _set_avatar_quote_status(
        tenant_id,
        generation_id=generation_id,
        running=True,
        complete=False,
        status="running",
        message="正在为数字人生成新人设语录",
        error="",
        version=getattr(settings, "version", 0),
        started_at=_now_iso(),
        finished_at="",
    )
    background_tasks.add_task(
        _refresh_tenant_avatar_quotes_background,
        tenant_id,
        settings,
        generation_id,
    )
    return status


def _refresh_tenant_avatar_quotes_background(
    tenant_id: str,
    settings,
    generation_id: str,
) -> None:
    result = _refresh_tenant_avatar_quotes(tenant_id, settings)
    with _avatar_quote_status_lock:
        current = _avatar_quote_statuses.get(normalize_tenant_id(tenant_id), {})
        if current.get("generationId") != generation_id:
            logger.info(
                "租户数字人语录旧生成任务结果已忽略: tenant=%s generation=%s current=%s",
                tenant_id,
                generation_id,
                current.get("generationId"),
            )
            return
    _set_avatar_quote_status(
        tenant_id,
        generation_id=generation_id,
        running=False,
        complete=True,
        status=result.get("status", "failed"),
        message=result.get("message", ""),
        error=result.get("error", ""),
        version=getattr(settings, "version", 0),
        finished_at=_now_iso(),
    )


def _set_avatar_quote_status(
    tenant_id: str,
    *,
    generation_id: str,
    running: bool,
    complete: bool,
    status: str,
    message: str,
    error: str = "",
    version: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict:
    tenant_id = normalize_tenant_id(tenant_id)
    with _avatar_quote_status_lock:
        previous = _avatar_quote_statuses.get(tenant_id, {})
        payload = {
            "generationId": generation_id,
            "running": bool(running),
            "complete": bool(complete),
            "status": status,
            "message": message,
            "error": error,
            "version": int(version or 0),
            "startedAt": started_at
            if started_at is not None
            else previous.get("startedAt", ""),
            "finishedAt": finished_at
            if finished_at is not None
            else previous.get("finishedAt", ""),
        }
        _avatar_quote_statuses[tenant_id] = payload
        logger.info(
            "租户数字人语录生成状态更新: tenant=%s status=%s running=%s version=%s",
            tenant_id,
            status,
            running,
            version,
        )
        return dict(payload)


def _get_avatar_quote_status(tenant_id: str) -> dict:
    tenant_id = normalize_tenant_id(tenant_id)
    with _avatar_quote_status_lock:
        status = _avatar_quote_statuses.get(tenant_id)
        if status:
            return dict(status)
    return {
        "generationId": "",
        "running": False,
        "complete": False,
        "status": "idle",
        "message": "",
        "error": "",
        "version": 0,
        "startedAt": "",
        "finishedAt": "",
    }


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _require_platform_admin(request: Request):
    context = tenant_context_from_request(request)
    platform_tenant_id = normalize_tenant_id(RUNTIME_DEFAULT_TENANT_ID)
    if (
        context.auth_method == "tenant-admin"
        and context.tenant_id == platform_tenant_id
    ):
        return context
    if (
        context.auth_method == "hmac"
        and context.credential_source == "legacy-default"
        and context.tenant_id == platform_tenant_id
    ):
        return context
    logger.warning(
        "平台管理员接口拒绝非平台主体: auth=%s tenant=%s principal=%s",
        context.auth_method,
        context.tenant_id,
        context.principal_id,
    )
    raise HTTPException(status_code=403, detail="platform administrator required")


def _binding_payload(binding) -> dict:
    return {
        "tenantId": binding.tenant_id,
        "tenantName": binding.tenant_name,
        "accountId": binding.account_id,
        "username": binding.username,
        "displayName": binding.display_name,
        "expiresAt": binding.expires_at,
    }
