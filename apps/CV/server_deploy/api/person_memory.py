"""Protected management endpoints for identity-bound person memory."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from core.person_memory import get_person_memory_service
from core.tenant import subject_belongs_to_tenant

router = APIRouter(prefix="/api/v1/person-memory", tags=["person-memory"])


class PersonMemoryFactCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    category: str = Field(default="personal_context", max_length=40)
    conversation_id: str = Field(default="manual-api", max_length=120)


@router.get("/status")
async def person_memory_status(request: Request) -> dict:
    tenant_context = getattr(request.state, "tenant_context", None)
    tenant_id = str(getattr(tenant_context, "tenant_id", ""))
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant authentication required")
    data = await run_in_threadpool(get_person_memory_service().status, tenant_id)
    return {"ok": True, "data": data}

@router.get("/{person_id}")
async def get_person_memory(request: Request, person_id: str) -> dict:
    _require_person_tenant(request, person_id)
    data = await run_in_threadpool(get_person_memory_service().get_memory, person_id)
    return {"ok": True, "data": data}


@router.post("/{person_id}/facts")
async def create_person_memory_fact(
    request: Request,
    person_id: str,
    payload: PersonMemoryFactCreateRequest,
) -> dict:
    _require_person_tenant(request, person_id)
    try:
        data = await run_in_threadpool(
            lambda: get_person_memory_service().remember_explicit(
                person_id=person_id,
                conversation_id=payload.conversation_id,
                content=payload.content,
                category=payload.category,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@router.delete("/{person_id}/facts/{fact_id}")
async def delete_person_memory_fact(
    request: Request, person_id: str, fact_id: str
) -> dict:
    _require_person_tenant(request, person_id)
    count = await run_in_threadpool(
        lambda: get_person_memory_service().retract_fact(
            person_id,
            fact_id,
            actor="signed-api",
        )
    )
    if count == 0:
        raise HTTPException(status_code=404, detail="active memory fact not found")
    return {"ok": True, "data": {"factsRetracted": count}}


@router.delete("/{person_id}")
async def clear_person_memory(request: Request, person_id: str) -> dict:
    _require_person_tenant(request, person_id)
    data = await run_in_threadpool(
        lambda: get_person_memory_service().clear_memory(person_id, actor="signed-api")
    )
    return {"ok": True, "data": data}


def _require_person_tenant(request: Request, person_id: str) -> str:
    tenant_context = getattr(request.state, "tenant_context", None)
    tenant_id = str(getattr(tenant_context, "tenant_id", ""))
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant authentication required")
    if not subject_belongs_to_tenant(person_id, tenant_id):
        raise HTTPException(status_code=404, detail="person memory not found")
    return tenant_id
