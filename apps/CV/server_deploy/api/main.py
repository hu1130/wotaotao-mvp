"""FastAPI app for employee enrollment and attendance integration."""

from __future__ import annotations

import json
import logging
import asyncio
import time
from typing import Callable

import anyio.to_thread
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import require_api_signature, tenant_context_from_request
from api.device_enrollment import router as device_enrollment_router
from api.tenant_admin import router as tenant_admin_router
from api.voice_auth import get_voice_ticket_store
from api.person_memory import router as person_memory_router
from api.schemas import (
    AttendanceRequest,
    ClientTaskCreateRequest,
    CaptureEnrollRequest,
    ClientTaskCompleteRequest,
    EmployeeEmbeddingEnrollRequest,
    EmployeeCreateRequest,
    EmployeeEnrollRequest,
    DialogChatRequest,
    DialogSceneReplyRequest,
    KnowledgeAskRequest,
    KnowledgeIndexRequest,
    KnowledgeSearchRequest,
    RemoteRecognitionFrameRequest,
    VoiceTicketRequest,
)
from api.services import (
    ApiError,
    AttendanceService,
    EmployeeService,
    PhotoCaptureService,
)
from config import (
    API_CORS_ORIGINS,
    API_THREADPOOL_TOKENS,
    DIALOG_CHAT_WARMUP_ENABLED,
    VOICE_PIPELINE_ENABLED,
    PERSON_SESSION_MEMORY_CONTEXT_MESSAGES,
    PERSON_SESSION_RECALL_CONTEXT_MESSAGES,
    PERSON_SESSION_SWEEP_SECONDS,
    PERSON_MEMORY_RECENT_CONTEXT_MESSAGES,
    RECOGNITION_MAX_CONCURRENCY,
    RECOGNITION_QUEUE_TIMEOUT_SECONDS,
    VOICE_MAX_CONCURRENCY,
    VOICE_QUEUE_TIMEOUT_SECONDS,
)
from core.concurrency import AsyncCapacityGate, CapacityExceeded
from core.device_identity.service import get_device_authentication_service
from core.device_identity.repository import DeviceIdentityRepository
from core.tenant_admin.service import get_tenant_admin_auth_service
from core.tenant_avatar import get_tenant_avatar_persona_service
from core.dialog_chat import DialogChatError, get_dialog_chat_service
from core.client_tasks import get_client_task_queue
from core.daily_quote_scheduler import DailyQuoteScheduler
from core.hrms_attendance_sync import get_hrms_attendance_syncer
from core.knowledge.service import KnowledgeError, KnowledgeService, get_knowledge_service
from core.remote_recognition import RemoteRecognitionService
from core.runtime_scope import RuntimeScope
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id
from core.person_sessions import get_person_conversation_manager
from core.speech_streaming.pipeline import VoicePipelineError
from core.speech_streaming.session_factory import create_voice_pipeline_session
from core.speech_streaming.volc_asr import VolcAsrError
from core.speech_streaming.volc_tts import VolcTtsError

logger = logging.getLogger("uvicorn.error")
remote_recognition_service: RemoteRecognitionService | None = None
daily_quote_scheduler: DailyQuoteScheduler | None = None
_last_recognition_frame_log_at: dict[str, float] = {}
person_session_sweeper: asyncio.Task | None = None
recognition_capacity = AsyncCapacityGate(
    "recognition",
    RECOGNITION_MAX_CONCURRENCY,
    RECOGNITION_QUEUE_TIMEOUT_SECONDS,
)
voice_capacity = AsyncCapacityGate(
    "voice",
    VOICE_MAX_CONCURRENCY,
    VOICE_QUEUE_TIMEOUT_SECONDS,
)

app = FastAPI(
    title="CV Company Integration API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RawBodyCacheMiddleware:
    """Cache HTTP bodies so signature verification can share multipart uploads."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        body_parts = []
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") != "http.request":
                continue
            body_parts.append(message.get("body", b""))
            more_body = bool(message.get("more_body", False))

        raw_body = b"".join(body_parts)
        scope["raw_body"] = raw_body
        sent = False

        async def replay_receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        await self.app(scope, replay_receive, send)


app.add_middleware(RawBodyCacheMiddleware)


@app.on_event("startup")
async def warmup_dialog_chat() -> None:
    global daily_quote_scheduler, remote_recognition_service, person_session_sweeper
    anyio.to_thread.current_default_thread_limiter().total_tokens = API_THREADPOOL_TOKENS
    logger.info(
        "API 并发容量已配置: threadpool=%d recognition=%d voice=%d",
        API_THREADPOOL_TOKENS,
        RECOGNITION_MAX_CONCURRENCY,
        VOICE_MAX_CONCURRENCY,
    )
    await run_in_threadpool(get_device_authentication_service)
    logger.info("设备注册与 Ed25519 认证服务已启动")
    tenant_admin_service = await run_in_threadpool(get_tenant_admin_auth_service)
    await run_in_threadpool(tenant_admin_service.ensure_legacy_default_account)
    logger.info("租户管理员认证服务已启动")
    remote_recognition_service = RemoteRecognitionService()
    get_person_conversation_manager()
    person_session_sweeper = asyncio.create_task(
        _person_session_sweep_loop(),
        name="person-session-sweeper",
    )
    daily_quote_scheduler = DailyQuoteScheduler(hour=6, minute=0)
    daily_quote_scheduler.start()
    logger.info("服务端每日语录调度已启动: 06:00")
    get_hrms_attendance_syncer().start_worker()
    if not DIALOG_CHAT_WARMUP_ENABLED:
        return
    try:
        await run_in_threadpool(lambda: get_dialog_chat_service().warmup())
    except Exception as exc:
        logger.warning("对话模型预热异常: %s", exc)


@app.on_event("shutdown")
async def shutdown_remote_recognition() -> None:
    global daily_quote_scheduler, remote_recognition_service, person_session_sweeper
    if person_session_sweeper is not None:
        person_session_sweeper.cancel()
        try:
            await person_session_sweeper
        except asyncio.CancelledError:
            pass
        person_session_sweeper = None
    if daily_quote_scheduler is not None:
        daily_quote_scheduler.stop()
        daily_quote_scheduler.join(timeout=5)
        daily_quote_scheduler = None
        logger.info("服务端每日语录调度已停止")
    if remote_recognition_service is not None:
        remote_recognition_service.shutdown()
        remote_recognition_service = None
    get_hrms_attendance_syncer().stop_worker()
    get_person_conversation_manager().close()


async def _person_session_sweep_loop() -> None:
    interval = max(0.25, PERSON_SESSION_SWEEP_SECONDS)
    while True:
        await asyncio.sleep(interval)
        try:
            get_person_conversation_manager().tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("人物会话定时清理异常")


app.include_router(
    person_memory_router,
    dependencies=[Depends(require_api_signature)],
)
app.include_router(device_enrollment_router)
app.include_router(tenant_admin_router)


def handle_api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ApiError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, KnowledgeError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DialogChatError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "company-integration-api"}


@app.get("/api/v1/employees", dependencies=[Depends(require_api_signature)])
async def list_employees(request: Request) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: EmployeeService(tenant_id).list_employees()
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/employees", dependencies=[Depends(require_api_signature)])
async def create_employee(request: Request, payload: EmployeeCreateRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: EmployeeService(tenant_id).create_employee(payload.name)
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/employees/enroll-local", dependencies=[Depends(require_api_signature)])
async def enroll_employee(request: Request, payload: EmployeeEnrollRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: EmployeeService(tenant_id).enroll_employee(
                payload.name,
                payload.photo_paths,
                payload.folder,
            )
        )
        await _notify_remote_employee_enrolled(
            payload.name, "enroll_photo_paths", tenant_id
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/employees/enroll-upload", dependencies=[Depends(require_api_signature)])
async def enroll_employee_from_upload(
    request: Request,
    name: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        logger.info(
            "员工录入上传开始: client=%s name=%s files=%d bytes=%d",
            request.client.host if request.client else "unknown",
            name,
            len(files or []),
            len(request.scope.get("raw_body") or b""),
        )
        upload_files = [(item.filename or "", item.file) for item in files]
        data = await run_in_threadpool(
            lambda: PhotoCaptureService(
                EmployeeService(tenant_id)
            ).enroll_from_uploaded_files(
                name,
                upload_files,
            )
        )
        logger.info(
            "员工录入上传完成: name=%s embeddings=%s photos=%s",
            name,
            data.get("embeddings"),
            data.get("photos"),
        )
        await _notify_remote_employee_enrolled(name, "enroll_upload", tenant_id)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.exception("员工录入上传失败: name=%s files=%d", name, len(files or []))
        raise handle_api_error(exc) from exc


@app.post("/api/v1/employees/enroll-embeddings", dependencies=[Depends(require_api_signature)])
async def enroll_employee_from_embeddings(
    request: Request, payload: EmployeeEmbeddingEnrollRequest
) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        logger.info(
            "员工向量录入开始: name=%s embeddings=%d",
            payload.name,
            len(payload.embeddings or []),
        )
        data = await run_in_threadpool(
            lambda: EmployeeService(tenant_id).enroll_employee_embeddings(
                payload.name,
                [item.model_dump(by_alias=True) for item in payload.embeddings],
            )
        )
        logger.info(
            "员工向量录入完成: name=%s embeddings=%s",
            payload.name,
            data.get("embeddings"),
        )
        await _notify_remote_employee_enrolled(
            payload.name, "enroll_embeddings", tenant_id
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.exception(
            "员工向量录入失败: name=%s embeddings=%d",
            payload.name,
            len(payload.embeddings or []),
        )
        raise handle_api_error(exc) from exc


@app.post("/api/v1/employees/capture-enroll", dependencies=[Depends(require_api_signature)])
async def capture_and_enroll(request: Request, payload: CaptureEnrollRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: PhotoCaptureService(EmployeeService(tenant_id)).capture_and_enroll(
                payload.name,
                payload.camera_index,
                payload.warmup_frames,
            )
        )
        await _notify_remote_employee_enrolled(
            payload.name, "capture_enroll", tenant_id
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.delete("/api/v1/employees/{name}", dependencies=[Depends(require_api_signature)])
async def delete_employee(request: Request, name: str) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: EmployeeService(tenant_id).delete_employee(name)
        )
        await run_in_threadpool(
            lambda: _remote_recognition().sync_employee_embeddings(name, tenant_id)
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/attendance/check-in", dependencies=[Depends(require_api_signature)])
async def check_in(request: Request, payload: AttendanceRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: AttendanceService(tenant_id).check_in(
                payload.name,
                payload.force,
            )
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/attendance/check-out", dependencies=[Depends(require_api_signature)])
async def check_out(request: Request, payload: AttendanceRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: AttendanceService(tenant_id).check_out(
                payload.name,
                payload.force,
            )
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.get("/api/v1/attendance/today/{name}", dependencies=[Depends(require_api_signature)])
async def today_records(request: Request, name: str) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: AttendanceService(tenant_id).today_records(name)
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/recognition/frame", dependencies=[Depends(require_api_signature)])
async def remote_recognition_frame(request: Request, payload: RemoteRecognitionFrameRequest) -> dict:
    global _last_recognition_frame_log_at
    try:
        auth_context = tenant_context_from_request(request)
        tenant_id = auth_context.tenant_id
        if (
            "tenant_id" in payload.model_fields_set
            and RuntimeScope.build(payload.tenant_id, payload.device_id).tenant_id
            != tenant_id
        ):
            raise HTTPException(status_code=403, detail="tenant scope mismatch")
        requested_device_id = RuntimeScope.build(tenant_id, payload.device_id).device_id
        if auth_context.auth_method == "device":
            if payload.device_id and requested_device_id != auth_context.device_id:
                raise HTTPException(status_code=403, detail="device scope mismatch")
            requested_device_id = auth_context.device_id
        scope = RuntimeScope.build(tenant_id, requested_device_id)
        now = time.time()
        should_log_frame = now - _last_recognition_frame_log_at.get(scope.key, 0.0) >= 5.0
        if should_log_frame:
            _last_recognition_frame_log_at[scope.key] = now
            logger.info(
                "远程识别收帧: client=%s scope=%s size=%dx%d faces=%d",
                request.client.host if request.client else "unknown",
                scope.key,
                payload.frame_width,
                payload.frame_height,
                len(payload.faces or []),
            )
        async with recognition_capacity.slot(scope.key):
            service = _remote_recognition()
            request_payload = payload.model_dump()
            request_payload["tenant_id"] = tenant_id
            data = await run_in_threadpool(
                lambda: service.process_frame(request_payload)
            )
            person_session = await run_in_threadpool(
                lambda: get_person_conversation_manager().observe(
                    scope.device_id,
                    data.get("faces") or [],
                    frame_width=payload.frame_width,
                    frame_height=payload.frame_height,
                    tenant_id=scope.tenant_id,
                )
            )
        data["person_session"] = person_session.to_dict()
        if should_log_frame:
            logger.info(
                "远程识别处理完成: scope=%s face_count=%d checked_in=%d db_person_count=%d today=%d",
                scope.key,
                int(data.get("face_count") or 0),
                len(data.get("checked_in_names") or []),
                int(data.get("db_person_count") or 0),
                int(data.get("today_count") or 0),
            )
        return {"ok": True, "data": data}
    except CapacityExceeded as exc:
        logger.warning("远程识别容量已满: scope=%s", exc.scope_key)
        raise HTTPException(
            status_code=429,
            detail="recognition capacity exceeded; retry shortly",
            headers={"Retry-After": "1"},
        ) from exc
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.get(
    "/api/v1/person-sessions/{device_id}",
    dependencies=[Depends(require_api_signature)],
)
async def person_session_status(request: Request, device_id: str) -> dict:
    tenant_id = tenant_context_from_request(request).tenant_id
    snapshot = get_person_conversation_manager().get(device_id, tenant_id=tenant_id)
    return {"ok": True, "data": snapshot.to_dict()}


@app.get("/api/v1/runtime/capacity", dependencies=[Depends(require_api_signature)])
async def runtime_capacity_status() -> dict:
    return {
        "ok": True,
        "data": {
            "threadpoolTokens": API_THREADPOOL_TOKENS,
            "gates": [recognition_capacity.snapshot(), voice_capacity.snapshot()],
        },
    }


@app.post("/api/v1/recognition/check-out", dependencies=[Depends(require_api_signature)])
async def remote_recognition_checkout(
    request: Request, payload: AttendanceRequest
) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        service = _remote_recognition()
        data = await run_in_threadpool(
            lambda: service.checkout(payload.name, tenant_id)
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


def _remote_recognition() -> RemoteRecognitionService:
    global remote_recognition_service
    if remote_recognition_service is None:
        remote_recognition_service = RemoteRecognitionService()
    return remote_recognition_service


async def _notify_remote_employee_enrolled(
    name: str, reason: str, tenant_id: str
) -> None:
    try:
        await run_in_threadpool(
            lambda: _remote_recognition().note_employee_enrolled(
                name, reason, tenant_id
            )
        )
    except Exception as exc:
        logger.warning(
            "远程识别录入后刷新失败: tenant=%s name=%s reason=%s error=%s",
            tenant_id,
            name,
            reason,
            exc,
        )


@app.get("/api/v1/knowledge/stats", dependencies=[Depends(require_api_signature)])
async def knowledge_stats(request: Request) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(lambda: get_knowledge_service(tenant_id).stats())
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/knowledge/index", dependencies=[Depends(require_api_signature)])
async def index_knowledge(request: Request, payload: KnowledgeIndexRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: get_knowledge_service(tenant_id).index_paths(
                payload.paths, reset=payload.reset
            )
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/knowledge/search", dependencies=[Depends(require_api_signature)])
async def search_knowledge(request: Request, payload: KnowledgeSearchRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        results = await run_in_threadpool(
            lambda: get_knowledge_service(tenant_id).search(
                payload.query,
                top_k=payload.top_k,
                min_score=payload.min_score,
            )
        )
        data = [KnowledgeService._result_to_dict(item) for item in results]
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/knowledge/ask", dependencies=[Depends(require_api_signature)])
async def ask_knowledge(request: Request, payload: KnowledgeAskRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: get_knowledge_service(tenant_id).answer(
                payload.question, top_k=payload.top_k
            )
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/dialog/chat", dependencies=[Depends(require_api_signature)])
async def dialog_chat(request: Request, payload: DialogChatRequest) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        data = await run_in_threadpool(
            lambda: get_dialog_chat_service().reply(payload.text, tenant_id)
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.post("/api/v1/dialog/scene-reply", dependencies=[Depends(require_api_signature)])
async def dialog_scene_reply(
    request: Request,
    payload: DialogSceneReplyRequest,
) -> dict:
    try:
        tenant_id = tenant_context_from_request(request).tenant_id
        answer = await run_in_threadpool(
            lambda: get_dialog_chat_service().scene_reply(
                scene=payload.scene,
                user_text=payload.user_text,
                tenant_id=tenant_id,
                context=payload.context,
                user_info=payload.user_info,
                required_facts=payload.required_facts,
                response_goal=payload.response_goal,
                constraints=payload.constraints,
            )
        )
        return {
            "ok": True,
            "data": {
                "tenantId": tenant_id,
                "scene": payload.scene,
                "answer": answer,
            },
        }
    except Exception as exc:
        raise handle_api_error(exc) from exc


@app.get("/api/v1/avatar/persona", dependencies=[Depends(require_api_signature)])
async def get_avatar_persona(request: Request) -> dict:
    tenant_id = tenant_context_from_request(request).tenant_id
    settings = await run_in_threadpool(
        get_tenant_avatar_persona_service().resolve,
        tenant_id,
    )
    return {"ok": True, "data": settings.to_public_dict()}


@app.get("/api/v1/client-tasks/next", dependencies=[Depends(require_api_signature)])
async def next_client_task(
    request: Request, device_id: str = "", supported_actions: str = ""
) -> dict:
    auth_context = tenant_context_from_request(request)
    tenant_id = auth_context.tenant_id
    if auth_context.auth_method == "device":
        if device_id and device_id != auth_context.device_id:
            raise HTTPException(status_code=403, detail="device scope mismatch")
        device_id = auth_context.device_id
    task = get_client_task_queue().claim_next(
        device_id,
        supported_actions=parse_csv_param(supported_actions),
        tenant_id=tenant_id,
    )
    return {"ok": True, "data": task.to_dict() if task else None}


@app.post("/api/v1/client-tasks", dependencies=[Depends(require_api_signature)])
async def create_client_task(request: Request, payload: ClientTaskCreateRequest) -> dict:
    auth_context = tenant_context_from_request(request)
    tenant_id = auth_context.tenant_id
    target_device_id = payload.target_device_id
    if auth_context.auth_method == "avatar-session":
        if payload.action != "capture_face_enroll":
            raise HTTPException(
                status_code=403,
                detail="avatar session can only create face capture tasks",
            )
        if target_device_id and target_device_id != auth_context.device_id:
            raise HTTPException(status_code=403, detail="device scope mismatch")
        target_device_id = auth_context.device_id
    if target_device_id:
        device = await run_in_threadpool(
            DeviceIdentityRepository().get_device,
            target_device_id,
        )
        if device is None or device.tenant_id != tenant_id or not device.active:
            raise HTTPException(status_code=404, detail="active tenant device not found")
    task = get_client_task_queue().create(
        payload.action,
        payload.payload or {},
        target_device_id=target_device_id,
        required_capabilities=payload.required_capabilities,
        tenant_id=tenant_id,
    )
    logger.info(
        "客户端任务接口创建: id=%s action=%s target=%s",
        task.id,
        task.action,
        task.target_device_id or "*",
    )
    return {"ok": True, "data": task.to_dict()}


@app.post("/api/v1/client-tasks/{task_id}/complete", dependencies=[Depends(require_api_signature)])
async def complete_client_task(
    request: Request, task_id: str, payload: ClientTaskCompleteRequest
) -> dict:
    tenant_id = tenant_context_from_request(request).tenant_id
    task = get_client_task_queue().complete(
        task_id,
        ok=payload.ok,
        result=payload.result,
        error=payload.error,
        tenant_id=tenant_id,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="client task not found")
    task_dict = task.to_dict()
    try:
        await run_in_threadpool(
            lambda: get_hrms_attendance_syncer().report_face_enroll_task_result(
                task_dict
            )
        )
    except Exception as exc:
        await run_in_threadpool(
            lambda: get_hrms_attendance_syncer().release_face_enroll_task_claim(
                task_dict
            )
        )
        logger.warning(
            "HRMS 人脸录入任务结果回传失败: task=%s action=%s error=%s",
            task.id,
            task.action,
            exc,
        )
    return {"ok": True, "data": task_dict}


@app.get("/api/v1/client-tasks/stats", dependencies=[Depends(require_api_signature)])
async def client_task_stats(request: Request) -> dict:
    tenant_id = tenant_context_from_request(request).tenant_id
    return {"ok": True, "data": get_client_task_queue().stats(tenant_id)}


def parse_csv_param(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@app.post("/api/v1/dialog/voice-ticket", dependencies=[Depends(require_api_signature)])
async def create_voice_ticket(request: Request, payload: VoiceTicketRequest) -> dict:
    auth_context = tenant_context_from_request(request)
    tenant_id = auth_context.tenant_id
    device_id = payload.device_id
    if auth_context.auth_method in {"device", "avatar-session"}:
        if device_id != auth_context.device_id:
            raise HTTPException(status_code=403, detail="device scope mismatch")
        device_id = auth_context.device_id
    try:
        token, binding = await run_in_threadpool(
            get_voice_ticket_store().issue,
            tenant_id,
            device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "data": {
            "ticket": token,
            "tenantId": binding.tenant_id,
            "deviceId": binding.device_id,
            "expiresAt": binding.expires_at,
        },
    }


@app.websocket("/api/v1/dialog/voice-stream")
async def dialog_voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    client_host = websocket.client.host if websocket.client else "unknown"
    try:
        async with voice_capacity.slot(f"client={client_host}"):
            await _serve_dialog_voice_stream(websocket)
    except CapacityExceeded:
        logger.warning("语音流容量已满: client=%s", client_host)
        await websocket.send_json(
            {"type": "error", "code": "voice_capacity_exceeded", "message": "语音服务繁忙，请稍后重试"}
        )
        await websocket.close(code=1013)


async def _serve_dialog_voice_stream(websocket: WebSocket) -> None:
    if not VOICE_PIPELINE_ENABLED:
        await websocket.send_json({"type": "error", "message": "voice pipeline is disabled"})
        await websocket.close()
        return

    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("语音流连接已建立: client=%s", client_host)
    active_client_turn_id = ""

    async def send_voice_payload(payload: dict) -> None:
        outgoing = dict(payload)
        if active_client_turn_id:
            outgoing.setdefault("turnId", active_client_turn_id)
        await websocket.send_json(outgoing)

    session = create_voice_pipeline_session(send_voice_payload)
    session_started = False
    turn_open = False
    turn_person_session = None
    bound_conversation_id = ""
    device_id = ""
    tenant_id = DEFAULT_TENANT_ID
    voice_authenticated = False
    connected_at = time.monotonic()
    audio_chunks = 0
    audio_bytes = 0
    last_audio_log_at = 0.0
    turn_finish_task: asyncio.Task | None = None
    pending_session_end_reason = ""

    async def settle_turn_finish_task() -> None:
        nonlocal turn_finish_task
        if turn_finish_task is not None and turn_finish_task.done():
            task = turn_finish_task
            turn_finish_task = None
            try:
                task.result()
            except asyncio.CancelledError:
                pass

    async def finalize_turn_state() -> None:
        nonlocal turn_open, turn_person_session, audio_chunks, audio_bytes
        nonlocal active_client_turn_id
        await settle_turn_finish_task()
        completed_turn = session.take_completed_turn()
        if completed_turn and turn_person_session is not None:
            current_person_session = get_person_conversation_manager().get(
                device_id, tenant_id=tenant_id
            )
            persistence_snapshot = (
                current_person_session
                if current_person_session.conversation_id
                == turn_person_session.conversation_id
                else turn_person_session
            )
            await run_in_threadpool(
                lambda: get_person_conversation_manager().append_turn(
                    persistence_snapshot,
                    user_text=completed_turn[0],
                    assistant_text=completed_turn[1],
                )
            )
        turn_open = False
        active_client_turn_id = ""
        turn_person_session = None
        audio_chunks = 0
        audio_bytes = 0

    async def close_if_session_release_pending() -> bool:
        nonlocal pending_session_end_reason
        if turn_open or not pending_session_end_reason:
            return False
        reason = pending_session_end_reason
        pending_session_end_reason = ""
        logger.info(
            "人物会话待释放语音长连接在轮次完成后关闭: device=%s conversation=%s reason=%s",
            device_id,
            bound_conversation_id or "(none)",
            reason,
        )
        await websocket.send_json({"type": "session_end", "reason": reason})
        return True

    async def request_session_release(reason: str, *, detail: str) -> bool:
        nonlocal pending_session_end_reason
        if turn_open:
            if pending_session_end_reason != reason:
                logger.info(
                    "人物会话释放已延迟到当前语音轮次完成: device=%s conversation=%s reason=%s detail=%s",
                    device_id,
                    bound_conversation_id or "(none)",
                    reason,
                    detail,
                )
            pending_session_end_reason = reason
            return False
        logger.info(
            "人物会话释放语音长连接: device=%s conversation=%s reason=%s detail=%s",
            device_id,
            bound_conversation_id or "(none)",
            reason,
            detail,
        )
        await websocket.send_json({"type": "session_end", "reason": reason})
        return True

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                if not voice_authenticated and time.monotonic() - connected_at > 10.0:
                    logger.warning("语音流认证超时: client=%s", client_host)
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "voice_auth_timeout",
                            "message": "语音连接认证超时",
                        }
                    )
                    await websocket.close(code=4401)
                    break
                if turn_finish_task is not None and turn_finish_task.done():
                    await settle_turn_finish_task()
                if await close_if_session_release_pending():
                    break
                if not device_id or not bound_conversation_id:
                    continue
                current = get_person_conversation_manager().get(
                    device_id, tenant_id=tenant_id
                )
                if current.conversation_id != bound_conversation_id:
                    should_close = await request_session_release(
                        "owner_changed",
                        detail=f"old={bound_conversation_id} current={current.conversation_id or '(none)'}",
                    )
                    if should_close:
                        break
                    continue
                if current.should_release_voice:
                    should_close = await request_session_release(
                        current.state.value,
                        detail=f"state={current.state.value}",
                    )
                    if should_close:
                        break
                    continue
                continue
            if message.get("type") == "websocket.disconnect":
                break
            if turn_finish_task is not None and turn_finish_task.done():
                await settle_turn_finish_task()
            if message.get("bytes") is not None:
                if not voice_authenticated:
                    logger.warning("语音流认证前收到音频: client=%s", client_host)
                    await websocket.close(code=4401)
                    break
                if not turn_open:
                    if session.supports_multiple_turns:
                        await session.prepare_next_turn()
                    turn_open = True
                    audio_chunks = 0
                    audio_bytes = 0
                    turn_person_session = get_person_conversation_manager().note_speech(
                        device_id, tenant_id=tenant_id
                    )
                elif audio_chunks == 0:
                    turn_person_session = get_person_conversation_manager().note_speech(
                        device_id, tenant_id=tenant_id
                    )
                if not session_started:
                    await session.start()
                    session_started = True
                audio_chunks += 1
                audio_bytes += len(message["bytes"] or b"")
                now = time.time()
                if now - last_audio_log_at >= 5.0:
                    last_audio_log_at = now
                    logger.info(
                        "语音流收到音频: client=%s chunks=%d bytes=%d",
                        client_host,
                        audio_chunks,
                        len(message["bytes"] or b""),
                    )
                await session.send_audio(message["bytes"])
                continue

            text = message.get("text")
            if text is None:
                continue
            if text.startswith("{"):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {}
                if not voice_authenticated and payload.get("type") != "context":
                    logger.warning(
                        "语音流认证前收到控制消息: client=%s type=%s",
                        client_host,
                        payload.get("type") or "unknown",
                    )
                    await websocket.close(code=4401)
                    break
                if payload.get("type") == "context":
                    requested_turn_id = str(payload.get("turnId") or "").strip()[:80]
                    if not requested_turn_id:
                        logger.warning("语音流缺少逻辑轮次标识: client=%s", client_host)
                        await websocket.close(code=4400)
                        break
                    metadata = payload.get("metadata") or {}
                    requested_device_id = str(
                        metadata.get("device_id") or metadata.get("deviceId") or ""
                    ).strip()[:80]
                    ticket = str(
                        metadata.get("voice_ticket")
                        or metadata.get("voiceTicket")
                        or ""
                    )
                    binding = await run_in_threadpool(
                        get_voice_ticket_store().consume,
                        ticket,
                        requested_device_id,
                    )
                    if binding is None:
                        logger.warning(
                            "语音流票据无效: client=%s device=%s",
                            client_host,
                            requested_device_id or "(empty)",
                        )
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "invalid_voice_ticket",
                                "message": "语音票据无效或已过期",
                            }
                        )
                        await websocket.close(code=4401)
                        break
                    claimed_tenant_id = normalize_tenant_id(
                        str(
                            metadata.get("tenant_id")
                            or metadata.get("tenantId")
                            or binding.tenant_id
                        )
                    )
                    if claimed_tenant_id != binding.tenant_id:
                        logger.warning(
                            "未认证语音流尝试跨租户访问: client=%s tenant=%s",
                            client_host,
                            claimed_tenant_id,
                        )
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "voice_ticket_tenant_mismatch",
                                "message": "语音票据与请求租户不匹配",
                            }
                        )
                        await websocket.close(code=4403)
                        break
                    tenant_id = binding.tenant_id
                    device_id = binding.device_id
                    active_client_turn_id = requested_turn_id
                    voice_authenticated = True
                    person_session = get_person_conversation_manager().get(
                        device_id, tenant_id=tenant_id
                    )
                    bound_conversation_id = person_session.conversation_id
                    remembered_context = await run_in_threadpool(
                        lambda: get_person_conversation_manager().recent_context(
                            person_session,
                            limit=max(
                                PERSON_SESSION_RECALL_CONTEXT_MESSAGES,
                                PERSON_MEMORY_RECENT_CONTEXT_MESSAGES,
                            ),
                        )
                    )
                    model_context = remembered_context[
                        -max(2, PERSON_SESSION_MEMORY_CONTEXT_MESSAGES) :
                    ]
                    logger.info(
                        "人物会话记忆恢复: device=%s conversation=%s owner=%s memory_read=%s model_messages=%d recall_messages=%d",
                        device_id,
                        person_session.conversation_id or "(none)",
                        person_session.owner_name or "(anonymous)",
                        person_session.memory_read_allowed,
                        len(model_context),
                        len(remembered_context),
                    )
                    session.set_context(
                        model_context
                        if person_session.has_owner
                        else (payload.get("items") or [])
                    )
                    session.set_person_memory_context(
                        remembered_context if person_session.has_owner else []
                    )
                    enriched_metadata = dict(metadata)
                    enriched_metadata["tenant_id"] = tenant_id
                    enriched_metadata["device_id"] = device_id
                    if person_session.has_owner:
                        enriched_metadata.update(
                            {
                                "conversation_id": person_session.conversation_id,
                                "person_id": person_session.owner_id,
                                "person_name": person_session.owner_name,
                            }
                        )
                    session.set_metadata(enriched_metadata)
                    session.set_person_context(
                        person_id=(
                            person_session.owner_id if person_session.has_owner else ""
                        ),
                        person_name=(
                            person_session.owner_name if person_session.has_owner else ""
                        ),
                        verified=person_session.has_owner,
                        memory_read_allowed=person_session.memory_read_allowed,
                        privacy_epoch=person_session.privacy_epoch,
                    )
                    await session.load_person_memory_context()
                    await websocket.send_json(
                        {
                            "type": "person_session",
                            **person_session.to_dict(),
                            "keepOpen": bool(
                                session.supports_multiple_turns
                                and person_session.has_owner
                            ),
                            "restoredContextMessages": len(model_context),
                            "restoredRecallMessages": len(remembered_context),
                        }
                    )
                    if not session_started:
                        await session.start()
                        session_started = True
                    turn_open = True
                    turn_person_session = person_session
                    continue
                if payload.get("type") == "metadata":
                    trusted_metadata = dict(payload)
                    trusted_metadata["tenant_id"] = tenant_id
                    trusted_metadata["device_id"] = device_id
                    session.set_metadata(trusted_metadata)
                    if not session_started:
                        await session.start()
                        session_started = True
                    continue
                if payload.get("type") == "playback_complete":
                    requested_turn_id = str(payload.get("turnId") or "").strip()[:80]
                    if requested_turn_id != active_client_turn_id:
                        logger.warning(
                            "语音流忽略过期播放确认: client=%s conversation=%s "
                            "expected_turn=%s received_turn=%s",
                            client_host,
                            session.conversation_id,
                            active_client_turn_id or "(none)",
                            requested_turn_id or "(missing)",
                        )
                        continue
                    if not turn_open:
                        logger.debug(
                            "语音流忽略重复播放确认: client=%s conversation=%s turn=%s",
                            client_host,
                            session.conversation_id,
                            payload.get("turnId") or "(missing)",
                        )
                        continue
                    if not session.is_turn_finished:
                        logger.warning(
                            "语音流过早收到播放确认: client=%s conversation=%s turn=%s",
                            client_host,
                            session.conversation_id,
                            payload.get("turnId") or "(missing)",
                        )
                        continue
                    logger.info(
                        "语音轮次播放完成，提交人物会话: client=%s conversation=%s turn=%s",
                        client_host,
                        session.conversation_id,
                        payload.get("turnId") or "(missing)",
                    )
                    await finalize_turn_state()
                    if await close_if_session_release_pending():
                        break
                    if not session.supports_multiple_turns or not bound_conversation_id:
                        await websocket.close()
                        break
                    continue
                if payload.get("type") == "interrupt":
                    requested_turn_id = str(payload.get("turnId") or "").strip()[:80]
                    if requested_turn_id != active_client_turn_id:
                        logger.warning(
                            "语音流忽略过期抢话: client=%s conversation=%s "
                            "expected_turn=%s received_turn=%s",
                            client_host,
                            session.conversation_id,
                            active_client_turn_id or "(none)",
                            requested_turn_id or "(missing)",
                        )
                        continue
                    if turn_finish_task is not None and not turn_finish_task.done():
                        turn_finish_task.cancel()
                        await asyncio.gather(turn_finish_task, return_exceptions=True)
                    turn_finish_task = None
                    played_ms = max(0, int(payload.get("playedMs") or 0))
                    reply_id = str(payload.get("replyId") or "")
                    interruption = (
                        payload.get("interruption")
                        if isinstance(payload.get("interruption"), dict)
                        else {}
                    )
                    previous_user_text = str(
                        interruption.get("userText")
                        or interruption.get("user_text")
                        or ""
                    ).strip()[:500]
                    assistant_text = str(
                        interruption.get("assistantText")
                        or interruption.get("assistant_text")
                        or ""
                    ).strip()[:900]
                    active_sentence = str(
                        interruption.get("activeSentence")
                        or interruption.get("active_sentence")
                        or ""
                    ).strip()[:500]
                    client_mode = str(
                        interruption.get("mode") or payload.get("mode") or ""
                    ).strip()[:40]
                    logger.info(
                        "语音流收到用户抢话: client=%s conversation=%s turn=%s "
                        "reply=%s played_ms=%s previous_user_chars=%s assistant_chars=%s mode=%s",
                        client_host,
                        session.conversation_id,
                        payload.get("turnId") or "(missing)",
                        reply_id[:12] or "(none)",
                        played_ms,
                        len(previous_user_text),
                        len(assistant_text),
                        client_mode or "(unknown)",
                    )
                    await session.interrupt(
                        reason="interrupted",
                        played_reply_id=reply_id,
                        played_ms=played_ms,
                        previous_user_text=previous_user_text,
                        assistant_text=assistant_text,
                        active_sentence=active_sentence,
                        client_mode=client_mode,
                    )
                    await finalize_turn_state()
                    continue
                if payload.get("type") == "turn_start":
                    if turn_open:
                        logger.warning(
                            "语音流忽略重复 turn_start: client=%s conversation=%s",
                            client_host,
                            session.conversation_id,
                        )
                        continue
                    requested_turn_id = str(payload.get("turnId") or "").strip()[:80]
                    if not requested_turn_id:
                        logger.warning(
                            "语音长连接拒绝无轮次标识的新一轮: client=%s conversation=%s",
                            client_host,
                            session.conversation_id,
                        )
                        continue
                    active_client_turn_id = requested_turn_id
                    if not session.supports_multiple_turns:
                        await websocket.send_json(
                            {"type": "error", "message": "backend requires a new websocket"}
                        )
                        break
                    turn_metadata = dict(payload.get("metadata") or {})
                    turn_metadata["tenant_id"] = tenant_id
                    turn_metadata["device_id"] = device_id
                    session.set_metadata(turn_metadata)
                    await session.prepare_next_turn()
                    turn_person_session = get_person_conversation_manager().note_speech(
                        device_id, tenant_id=tenant_id
                    )
                    turn_open = True
                    audio_chunks = 0
                    audio_bytes = 0
                    logger.info(
                        "语音长连接开始下一轮: client=%s conversation=%s owner=%s",
                        client_host,
                        session.conversation_id,
                        turn_person_session.owner_name or "(anonymous)",
                    )
                    continue
            if text == "stop":
                if not turn_open:
                    logger.debug("语音流忽略已完成轮次的 stop: client=%s", client_host)
                    continue
                logger.info(
                    "语音流收到结束指令: client=%s chunks=%d bytes=%d",
                    client_host,
                    audio_chunks,
                    audio_bytes,
                )
                if not session_started or (
                    audio_bytes < 8000 and not session.supports_multiple_turns
                ):
                    logger.info(
                        "语音流忽略过短音频: client=%s chunks=%d bytes=%d",
                        client_host,
                        audio_chunks,
                        audio_bytes,
                    )
                    await websocket.send_json({"type": "done", "reason": "empty_asr"})
                    await finalize_turn_state()
                    if not session.supports_multiple_turns or not bound_conversation_id:
                        await websocket.close()
                        break
                else:
                    if turn_finish_task is None or turn_finish_task.done():
                        turn_finish_task = asyncio.create_task(
                            session.finish_audio(),
                            name=f"voice-finish-{session.conversation_id}",
                        )
                continue
    except WebSocketDisconnect:
        pass
    except (VolcAsrError, VolcTtsError, VoicePipelineError, DialogChatError) as exc:
        logger.warning("流式语音对话失败: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    except Exception as exc:
        logger.exception("流式语音对话异常: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        logger.info("语音流连接关闭: client=%s chunks=%d bytes=%d", client_host, audio_chunks, audio_bytes)
        if turn_finish_task is not None and not turn_finish_task.done():
            turn_finish_task.cancel()
            await asyncio.gather(turn_finish_task, return_exceptions=True)
        await session.close()
