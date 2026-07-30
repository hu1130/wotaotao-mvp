"""Validated tenant avatar persona resolution."""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Any

from config import (
    DIALOG_CHAT_SYSTEM_PROMPT,
    REALTIME_DIALOG_BOT_NAME,
    REALTIME_DIALOG_SPEAKING_STYLE,
    REALTIME_DIALOG_SYSTEM_ROLE,
    VOICE_ASSISTANT_NAME,
    VOICE_ASSISTANT_WAKE_ALIASES,
)
from core.redis_client import get_redis_client
from core.tenant import normalize_tenant_id

from .models import AvatarPersonaSettings, TenantAvatarPersona
from .repository import TenantAvatarPersonaRepository


logger = logging.getLogger(__name__)

_SPACE_RE = re.compile(r"\s+")
_DEFAULT_PERSONALITY = "开朗、亲切、有一点害羞"
_DEFAULT_SPEAKING_TONE = (
    "自然、简短、亲切，像真人前台一样温柔活泼，有自然停顿，适合语音播报"
)
_CACHE_TTL_SECONDS = 30


class TenantAvatarPersonaService:
    def __init__(
        self,
        repository: Any | None = None,
        cache: Any | None = None,
        *,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self.repository = repository or TenantAvatarPersonaRepository()
        self.cache = cache
        if self.cache is None:
            try:
                self.cache = get_redis_client()
            except Exception as exc:
                logger.warning("租户数字人人设 Redis 缓存初始化失败，改用 MySQL: %s", exc)
        self.cache_ttl_seconds = max(5, int(cache_ttl_seconds))

    @staticmethod
    def _cache_key(tenant_id: str) -> str:
        return f"avatar-persona:{tenant_id}:v1"

    def get_persona(self, tenant_id: str) -> TenantAvatarPersona | None:
        tenant_id = normalize_tenant_id(tenant_id)
        cached = self._cache_get(tenant_id)
        if cached is not None:
            return cached
        persona = self.repository.get(tenant_id)
        if persona is not None:
            self._cache_put(persona)
        return persona

    def resolve(self, tenant_id: str) -> AvatarPersonaSettings:
        tenant_id = normalize_tenant_id(tenant_id)
        persona = self.get_persona(tenant_id)
        if persona is None:
            return self._default_settings(tenant_id)
        if not self._has_custom_values(persona):
            settings = self._default_settings(tenant_id)
            return AvatarPersonaSettings(
                **{**asdict(settings), "version": persona.version}
            )

        assistant_name = persona.assistant_name or VOICE_ASSISTANT_NAME
        has_custom_name = self._uses_custom_assistant_name(persona.assistant_name)
        custom_wake_aliases = self._filter_aliases_for_assistant_name(
            persona.wake_aliases,
            has_custom_name=has_custom_name,
        )
        wake_aliases = self._resolve_wake_aliases(
            assistant_name,
            custom_wake_aliases,
            include_default_aliases=not has_custom_name,
        )
        personality = persona.personality or _DEFAULT_PERSONALITY
        speaking_tone = persona.speaking_tone or _DEFAULT_SPEAKING_TONE
        extra = persona.extra_instructions
        system_role = self._build_system_role(
            assistant_name=assistant_name,
            wake_aliases=wake_aliases,
            personality=personality,
            speaking_tone=speaking_tone,
            extra_instructions=extra,
        )
        chat_prompt = self._build_chat_system_prompt(
            assistant_name=assistant_name,
            wake_aliases=wake_aliases,
            personality=personality,
            speaking_tone=speaking_tone,
            extra_instructions=extra,
        )
        speaking_style = self._build_speaking_style(
            personality=personality,
            speaking_tone=speaking_tone,
            extra_instructions=extra,
        )
        return AvatarPersonaSettings(
            tenant_id=tenant_id,
            assistant_name=assistant_name,
            wake_aliases=wake_aliases,
            custom_wake_aliases=custom_wake_aliases,
            system_role=system_role,
            chat_system_prompt=chat_prompt,
            speaking_style=speaking_style,
            personality=personality,
            speaking_tone=speaking_tone,
            extra_instructions=extra,
            customized=True,
            version=persona.version,
        )

    def save(
        self,
        *,
        tenant_id: str,
        assistant_name: str = "",
        personality: str = "",
        speaking_tone: str = "",
        extra_instructions: str = "",
        wake_aliases: list[str] | tuple[str, ...] | None = None,
    ) -> TenantAvatarPersona:
        tenant_id = normalize_tenant_id(tenant_id)
        clean_assistant_name = self._clean_text(assistant_name, 40)
        clean_wake_aliases = self._clean_aliases(wake_aliases or ())
        clean_wake_aliases = self._filter_aliases_for_assistant_name(
            clean_wake_aliases,
            has_custom_name=self._uses_custom_assistant_name(clean_assistant_name),
        )
        persona = TenantAvatarPersona(
            tenant_id=tenant_id,
            assistant_name=clean_assistant_name,
            personality=self._clean_text(personality, 300),
            speaking_tone=self._clean_text(speaking_tone, 300),
            extra_instructions=self._clean_text(extra_instructions, 600),
            wake_aliases=clean_wake_aliases,
        )
        saved = self.repository.upsert(persona)
        self._invalidate(tenant_id)
        logger.info(
            "租户数字人人设已更新: tenant=%s name=%s aliases=%d version=%s",
            tenant_id,
            saved.assistant_name or "(default)",
            len(saved.wake_aliases),
            saved.version,
        )
        return saved

    def _default_settings(self, tenant_id: str) -> AvatarPersonaSettings:
        aliases = tuple(VOICE_ASSISTANT_WAKE_ALIASES)
        return AvatarPersonaSettings(
            tenant_id=tenant_id,
            assistant_name=REALTIME_DIALOG_BOT_NAME or VOICE_ASSISTANT_NAME,
            wake_aliases=aliases,
            custom_wake_aliases=tuple(),
            system_role=REALTIME_DIALOG_SYSTEM_ROLE,
            chat_system_prompt=DIALOG_CHAT_SYSTEM_PROMPT,
            speaking_style=REALTIME_DIALOG_SPEAKING_STYLE,
            personality="",
            speaking_tone="",
            extra_instructions="",
            customized=False,
            version=0,
        )

    @classmethod
    def _build_system_role(
        cls,
        *,
        assistant_name: str,
        wake_aliases: tuple[str, ...],
        personality: str,
        speaking_tone: str,
        extra_instructions: str,
    ) -> str:
        parts = [
            f"你是公司前台数字人，名字叫{assistant_name}。",
            f"你的正式名字只有{assistant_name}。被问到你是谁、你叫什么或你的名字时，"
            f"必须用第一人称回答“我叫{assistant_name}”或“我是{assistant_name}”，不要说“你叫{assistant_name}”。",
            "不要自称任何旧名字、默认名字或其他名字。",
            f"用户喊“{'、'.join(wake_aliases)}”是在叫你，你要知道这是你的名字。",
            "你正在接待来访者和同事。",
            f"你的性格设定：{personality}。",
            f"你的说话语气：{speaking_tone}。",
            "说话要有真人感，像日常聊天一样有自然的停顿和节奏，不要像朗读课文。",
        ]
        if extra_instructions:
            parts.append(f"补充人设要求：{extra_instructions}")
        return "".join(parts)

    @classmethod
    def _build_chat_system_prompt(
        cls,
        *,
        assistant_name: str,
        wake_aliases: tuple[str, ...],
        personality: str,
        speaking_tone: str,
        extra_instructions: str,
    ) -> str:
        parts = [
            f"你是公司前台数字人，名字叫{assistant_name}。",
            f"你的正式名字只有{assistant_name}。被问到你是谁、你叫什么或你的名字时，"
            f"必须用第一人称回答“我叫{assistant_name}”或“我是{assistant_name}”，不要说“你叫{assistant_name}”。",
            "不要自称任何旧名字、默认名字或其他名字。",
            f"用户喊“{'、'.join(wake_aliases)}”是在叫你。",
            f"你的性格设定：{personality}。",
            f"你的说话语气：{speaking_tone}。",
            "回答要自然、简短、亲切，适合语音播报。每次回复一到三句话，不要输出 Markdown。",
        ]
        if extra_instructions:
            parts.append(f"补充人设要求：{extra_instructions}")
        return "".join(parts)

    @staticmethod
    def _has_custom_values(persona: TenantAvatarPersona) -> bool:
        return any(
            (
                persona.assistant_name,
                persona.personality,
                persona.speaking_tone,
                persona.extra_instructions,
                persona.wake_aliases,
            )
        )

    @staticmethod
    def _build_speaking_style(
        *,
        personality: str,
        speaking_tone: str,
        extra_instructions: str,
    ) -> str:
        additions = []
        if personality:
            additions.append(f"当前租户设定的人设性格：{personality}")
        if speaking_tone:
            additions.append(f"当前租户设定的说话语气：{speaking_tone}")
        if extra_instructions:
            additions.append(f"补充表达要求：{extra_instructions}")
        if not additions:
            return REALTIME_DIALOG_SPEAKING_STYLE[:4000]
        style = (
            "严格优先服从当前租户控制台设定的人设性格、说话语气和补充要求。"
            "回复要简短自然，每次一到两句话，适合实时语音沟通，不要长篇解释。\n"
            + "\n".join(additions)
        )
        return style[:4000]

    @classmethod
    def _resolve_wake_aliases(
        cls,
        assistant_name: str,
        aliases: tuple[str, ...],
        *,
        include_default_aliases: bool = True,
    ) -> tuple[str, ...]:
        values = list(aliases)
        if assistant_name:
            generated = [assistant_name]
            if not assistant_name.startswith("小"):
                generated.append(f"小{assistant_name}")
            values = [*generated, *values]
        if include_default_aliases:
            values.extend(VOICE_ASSISTANT_WAKE_ALIASES)
        return cls._clean_aliases(values) or tuple(VOICE_ASSISTANT_WAKE_ALIASES)

    @classmethod
    def _filter_aliases_for_assistant_name(
        cls,
        aliases: tuple[str, ...],
        *,
        has_custom_name: bool,
    ) -> tuple[str, ...]:
        if not has_custom_name:
            return tuple(aliases)
        default_aliases = set(cls._clean_aliases(tuple(VOICE_ASSISTANT_WAKE_ALIASES)))
        return tuple(alias for alias in aliases if alias not in default_aliases)

    @classmethod
    def _uses_custom_assistant_name(cls, assistant_name: str) -> bool:
        name = cls._clean_text(assistant_name, 40)
        if not name:
            return False
        default_names = cls._clean_aliases(
            (
                VOICE_ASSISTANT_NAME,
                REALTIME_DIALOG_BOT_NAME,
                *VOICE_ASSISTANT_WAKE_ALIASES,
            )
        )
        return name not in default_names

    @classmethod
    def _clean_aliases(cls, aliases: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        cleaned = []
        for item in aliases:
            value = cls._clean_text(str(item), 30)
            if not value or value in cleaned:
                continue
            cleaned.append(value)
            if len(cleaned) >= 8:
                break
        return tuple(cleaned)

    @staticmethod
    def _clean_text(value: str, max_chars: int) -> str:
        value = _SPACE_RE.sub(" ", (value or "").strip())
        value = value.replace("\x00", "")
        return value[:max(1, max_chars)]

    def _cache_get(self, tenant_id: str) -> TenantAvatarPersona | None:
        if self.cache is None:
            return None
        try:
            raw = self.cache.get(self._cache_key(tenant_id))
            if not raw:
                return None
            value = json.loads(raw)
            for field in ("created_at", "updated_at"):
                if value.get(field):
                    value[field] = datetime.fromisoformat(value[field])
            value["wake_aliases"] = tuple(value.get("wake_aliases") or ())
            return TenantAvatarPersona(**value)
        except Exception as exc:
            logger.warning("租户数字人人设缓存读取失败，回源 MySQL: tenant=%s error=%s", tenant_id, exc)
            return None

    def _cache_put(self, persona: TenantAvatarPersona) -> None:
        if self.cache is None:
            return
        try:
            self.cache.setex(
                self._cache_key(persona.tenant_id),
                self.cache_ttl_seconds,
                json.dumps(asdict(persona), ensure_ascii=False, default=_json_default),
            )
        except Exception as exc:
            logger.warning(
                "租户数字人人设缓存写入失败: tenant=%s error=%s",
                persona.tenant_id,
                exc,
            )

    def _invalidate(self, tenant_id: str) -> None:
        if self.cache is None:
            return
        try:
            self.cache.delete(self._cache_key(tenant_id))
        except Exception as exc:
            logger.warning("租户数字人人设缓存失效失败: tenant=%s error=%s", tenant_id, exc)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


_service: TenantAvatarPersonaService | None = None
_service_lock = threading.Lock()


def get_tenant_avatar_persona_service() -> TenantAvatarPersonaService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = TenantAvatarPersonaService()
        return _service
