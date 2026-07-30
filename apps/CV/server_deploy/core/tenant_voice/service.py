"""Validated, cached resolution of tenant-specific Omni voice settings."""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from config import (
    REALTIME_DIALOG_MODEL,
    REALTIME_DIALOG_RESOURCE_ID,
    REALTIME_DIALOG_SPEAKER,
    REALTIME_DIALOG_SPEAKING_STYLE,
    VOICE_CLONE_PLATFORM_ENABLED,
    VOICE_PROFILE_CACHE_TTL_SECONDS,
    VOICE_PROFILE_PROBE_TTL_SECONDS,
    VOICE_SHARED_PROFILE_TENANT_ID,
)
from core.redis_client import get_redis_client
from core.tenant import normalize_tenant_id

from .models import OmniSessionSettings, TenantVoiceProfile
from .repository import TenantVoiceProfileRepository


logger = logging.getLogger(__name__)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VoiceProfileUnavailable(RuntimeError):
    pass


class TenantVoiceProfileService:
    def __init__(
        self,
        repository: Any | None = None,
        cache: Any | None = None,
        platform_enabled: bool | None = None,
        *,
        cache_ttl_seconds: int = VOICE_PROFILE_CACHE_TTL_SECONDS,
        probe_ttl_seconds: int = VOICE_PROFILE_PROBE_TTL_SECONDS,
        shared_profile_tenant_id: str = VOICE_SHARED_PROFILE_TENANT_ID,
    ) -> None:
        self.repository = repository or TenantVoiceProfileRepository()
        self.cache = cache
        if self.cache is None:
            try:
                self.cache = get_redis_client()
            except Exception as exc:
                logger.warning("租户音色 Redis 缓存初始化失败，改用 MySQL: %s", exc)
        self.platform_enabled = (
            VOICE_CLONE_PLATFORM_ENABLED
            if platform_enabled is None
            else bool(platform_enabled)
        )
        self.cache_ttl_seconds = max(5, int(cache_ttl_seconds))
        self.probe_ttl_seconds = int(probe_ttl_seconds)
        self.shared_profile_tenant_id = normalize_tenant_id(
            shared_profile_tenant_id
        )

    @staticmethod
    def _cache_key(tenant_id: str) -> str:
        return f"voice-profile:{tenant_id}:v1"

    def get_profile(self, tenant_id: str) -> TenantVoiceProfile | None:
        tenant_id = normalize_tenant_id(tenant_id)
        cached = self._cache_get(tenant_id)
        if cached is not None:
            return cached
        profile = self.repository.get(tenant_id)
        if profile is not None:
            self._cache_put(profile)
        return profile

    def resolve(self, tenant_id: str) -> OmniSessionSettings:
        tenant_id = normalize_tenant_id(tenant_id)
        profile = self.get_profile(tenant_id)
        shared = False
        if profile is None and tenant_id != self.shared_profile_tenant_id:
            profile = self.get_profile(self.shared_profile_tenant_id)
            shared = profile is not None
        if profile is None:
            return self._global_fallback(tenant_id)
        clone_enabled = bool(
            self.platform_enabled
            and profile.enabled
            and profile.status == "ready"
            and profile.probe_is_fresh(self.probe_ttl_seconds)
        )
        if self.platform_enabled and profile.enabled and not clone_enabled:
            logger.error(
                "租户克隆音色配置不可用，使用租户默认音色: tenant=%s status=%s "
                "probe_at=%s version=%s",
                tenant_id,
                profile.status,
                profile.last_probe_at or "(missing)",
                profile.version,
            )
        settings = profile.to_settings(clone_enabled=clone_enabled)
        if shared:
            settings = replace(settings, tenant_id=tenant_id)
            logger.debug(
                "租户使用平台共享音色: tenant=%s shared_profile=%s version=%s clone=%s",
                tenant_id,
                self.shared_profile_tenant_id,
                settings.profile_version,
                settings.clone_enabled,
            )
        return settings

    def register(self, profile: TenantVoiceProfile) -> TenantVoiceProfile:
        profile = self._validate_profile(profile)
        saved = self.repository.register(profile)
        self._invalidate(saved.tenant_id)
        logger.info(
            "租户克隆音色已登记: tenant=%s speaker=%s status=%s version=%s",
            saved.tenant_id,
            mask_speaker_id(saved.speaker_id),
            saved.status,
            saved.version,
        )
        return saved

    def set_enabled(self, tenant_id: str, enabled: bool) -> TenantVoiceProfile:
        tenant_id = normalize_tenant_id(tenant_id)
        current = self.repository.get(tenant_id)
        if current is None:
            raise ValueError("tenant voice profile not found")
        if enabled:
            if current.status != "ready":
                raise ValueError("only a ready voice profile can be enabled")
            if not current.probe_is_fresh(self.probe_ttl_seconds):
                raise ValueError("voice profile probe is missing or expired")
        saved = self.repository.set_enabled(tenant_id, enabled)
        if saved is None:
            raise ValueError("tenant voice profile not found")
        self._invalidate(tenant_id)
        logger.info(
            "租户克隆音色开关已更新: tenant=%s enabled=%s speaker=%s version=%s",
            tenant_id,
            saved.enabled,
            mask_speaker_id(saved.speaker_id),
            saved.version,
        )
        return saved

    @staticmethod
    def _validate_profile(profile: TenantVoiceProfile) -> TenantVoiceProfile:
        tenant_id = normalize_tenant_id(profile.tenant_id)
        if profile.provider != "volcengine":
            raise ValueError("provider must be volcengine")
        if not profile.speaker_id.startswith("S_"):
            raise ValueError("speaker_id must start with S_")
        if profile.omni_model != "1.2.1.1":
            raise ValueError("O2.0 omni model must be 1.2.1.1")
        if profile.realtime_resource_id != "volc.speech.dialog":
            raise ValueError("realtime resource must be volc.speech.dialog")
        if profile.training_resource_id != "seed-icl-2.0":
            raise ValueError("training resource must be seed-icl-2.0")
        if profile.tts_2_0_model != "expressive":
            raise ValueError("tts_2_0_model must be expressive")
        if not _SHA256_RE.fullmatch(profile.sample_sha256):
            raise ValueError("sample_sha256 must be 64 lowercase hex characters")
        if not profile.consent_reference.strip():
            raise ValueError("consent_reference is required")
        if profile.status not in {"draft", "probing", "ready", "degraded", "disabled"}:
            raise ValueError("invalid voice profile status")
        style = profile.speaking_style
        if not style or len(style) > 800:
            raise ValueError("speech persona speaking_style must contain 1-800 characters")
        if profile.status == "ready" and profile.last_probe_at is None:
            raise ValueError("ready voice profile requires last_probe_at")
        return TenantVoiceProfile(**{**asdict(profile), "tenant_id": tenant_id})

    def _global_fallback(self, tenant_id: str) -> OmniSessionSettings:
        return OmniSessionSettings(
            tenant_id=tenant_id,
            speaker_id=REALTIME_DIALOG_SPEAKER,
            fallback_speaker_id=REALTIME_DIALOG_SPEAKER,
            model=REALTIME_DIALOG_MODEL,
            realtime_resource_id=REALTIME_DIALOG_RESOURCE_ID,
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="",
            speaking_style=REALTIME_DIALOG_SPEAKING_STYLE,
            profile_version=0,
            clone_enabled=False,
        )

    def _cache_get(self, tenant_id: str) -> TenantVoiceProfile | None:
        if self.cache is None:
            return None
        try:
            raw = self.cache.get(self._cache_key(tenant_id))
            if not raw:
                return None
            value = json.loads(raw)
            for field in ("last_probe_at", "created_at", "updated_at"):
                if value.get(field):
                    value[field] = datetime.fromisoformat(value[field])
            return TenantVoiceProfile(**value)
        except Exception as exc:
            logger.warning("租户音色缓存读取失败，回源 MySQL: tenant=%s error=%s", tenant_id, exc)
            return None

    def _cache_put(self, profile: TenantVoiceProfile) -> None:
        if self.cache is None:
            return
        try:
            self.cache.setex(
                self._cache_key(profile.tenant_id),
                self.cache_ttl_seconds,
                json.dumps(asdict(profile), ensure_ascii=False, default=_json_default),
            )
        except Exception as exc:
            logger.warning(
                "租户音色缓存写入失败: tenant=%s error=%s",
                profile.tenant_id,
                exc,
            )

    def _invalidate(self, tenant_id: str) -> None:
        if self.cache is None:
            return
        try:
            self.cache.delete(self._cache_key(tenant_id))
        except Exception as exc:
            logger.warning("租户音色缓存失效失败: tenant=%s error=%s", tenant_id, exc)


def mask_speaker_id(speaker_id: str) -> str:
    value = (speaker_id or "").strip()
    if len(value) <= 7:
        return value[:3] + "…"
    return value[:6] + "…"


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


_service: TenantVoiceProfileService | None = None
_service_lock = threading.Lock()


def get_tenant_voice_profile_service() -> TenantVoiceProfileService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = TenantVoiceProfileService()
        return _service
