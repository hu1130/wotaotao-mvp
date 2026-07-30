"""Browser-facing Volcengine Omni S2S session with business routing and RAG."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from config import (
    DIALOG_CHAT_DEFAULT_COMPANY_RAG_MIN_SCORE,
    DIALOG_CHAT_INTENT_EMBEDDING_ENABLED,
    DIALOG_CHAT_INTENT_EMBEDDING_MIN_SCORE,
    REALTIME_DIALOG_ACCESS_KEY,
    REALTIME_DIALOG_APP_KEY,
    REALTIME_DIALOG_APP_ID,
    REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS,
    REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS,
    REALTIME_DIALOG_BASE_URL,
    REALTIME_DIALOG_BOT_NAME,
    REALTIME_DIALOG_CITY,
    REALTIME_DIALOG_DYNAMIC_NO_CACHE,
    REALTIME_DIALOG_ENABLE_CUSTOM_VAD,
    REALTIME_DIALOG_ENABLE_LOUDNESS_NORM,
    REALTIME_DIALOG_END_SMOOTH_WINDOW_MS,
    REALTIME_DIALOG_LOUDNESS_RATE,
    REALTIME_DIALOG_MODEL,
    REALTIME_DIALOG_OUTPUT_FORMAT,
    REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
    REALTIME_DIALOG_PING_INTERVAL_SECONDS,
    REALTIME_DIALOG_PING_TIMEOUT_SECONDS,
    REALTIME_DIALOG_CLOSE_TIMEOUT_SECONDS,
    REALTIME_DIALOG_RAG_COMPLETION_TIMEOUT_SECONDS,
    REALTIME_DIALOG_RAG_ENABLED,
    REALTIME_DIALOG_RAG_FIRST_AUDIO_TIMEOUT_SECONDS,
    REALTIME_DIALOG_RAG_MAX_CHARS,
    REALTIME_DIALOG_RAG_MIN_SCORE,
    REALTIME_DIALOG_RAG_SERIAL_TIMEOUT_SECONDS,
    REALTIME_DIALOG_RAG_TOP_K,
    REALTIME_DIALOG_RESOURCE_ID,
    REALTIME_DIALOG_SPEAKER,
    REALTIME_DIALOG_SPEAKING_STYLE,
    REALTIME_DIALOG_SPEECH_RATE,
    REALTIME_DIALOG_SYSTEM_ROLE,
)
from core.dialog_silence import (
    ACTION_MUTE,
    ACTION_SUPPRESS,
    ACTION_WAKE,
    DialogSilenceResult,
)
from core.dialog_chat import classify_local_quick_reply_scene
from core.dialog_intent_router import DialogIntentRouter
from core.knowledge.service import get_knowledge_service
from core.person_memory import get_person_memory_service
from core.person_sessions.context_intent import (
    PersonContextIntentRouter,
    conversation_recall_day_label,
    conversation_recall_day_offset,
)
from core.speech_streaming.pipeline import (
    Sender,
    VoicePipelineError,
    VoicePipelineSession,
    assemble_wav_audio,
    normalize_tts_text,
)
from core.speech_streaming.volc_realtime import (
    VolcRealtimeDialogClient,
    VolcRealtimeDialogConfig,
    VolcRealtimeDialogError,
)
from core.speech_streaming.tts_expectation import (
    ExternalRagTimeout,
    TtsExpectation,
    TtsExpectationError,
)
from core.tenant_voice.models import OmniSessionSettings
from core.tenant_voice.service import (
    get_tenant_voice_profile_service,
    mask_speaker_id,
)
from core.tenant_avatar import get_tenant_avatar_persona_service


logger = logging.getLogger(__name__)

OMNI_MODEL = "1.2.1.1"
TTS_TYPE_DEFAULT = "default"
TTS_TYPE_EXTERNAL_RAG = "external_rag"
TTS_TYPE_CHAT_TEXT = "chat_tts_text"
TTS_TYPE_AUDIT = "audit_content_risky"

ARBITRATION_ROUTING = "routing"
ARBITRATION_EXTERNAL_PENDING = "external_pending"
ARBITRATION_EXTERNAL_COMMITTED = "external_committed"
ARBITRATION_DEFAULT = "default"

PENDING_DEFAULT_STATES = {
    ARBITRATION_ROUTING,
    ARBITRATION_EXTERNAL_PENDING,
}

class OmniVoicePipelineSession(VoicePipelineSession):
    """Adapts an Omni S2S session to the existing browser voice protocol."""

    def __init__(self, send_json: Sender):
        # The parent owns the shared command/action routing. Its cascade clients are
        # intentionally never connected by this subclass.
        super().__init__(send_json)
        self.transport: VolcRealtimeDialogClient | None = None
        self._receive_task: asyncio.Task | None = None
        self._route_task: asyncio.Task | None = None
        self._browser_send_lock = asyncio.Lock()
        self._finished = asyncio.Event()
        self._asr_ended = asyncio.Event()
        self._started = False
        self._input_ended = False
        self._last_user_text = ""
        self._response_mode = "routing"
        self._arbitration_state = ARBITRATION_ROUTING
        self._default_fallback_released = False
        self._current_tts_type = ""
        self._current_tts_text = ""
        self._current_reply_id = ""
        self._current_audio_chunks: list[bytes] = []
        self._pending_response_text = ""
        self._reply_texts: dict[str, str] = {}
        self._allowed_reply_ids: set[str] = set()
        self._allowed_reply_order: list[str] = []
        self._emitted_reply_texts: dict[str, str] = {}
        self._response_types_seen: set[str] = set()
        self._dynamic_session_nonce = ""
        self._pending_default_sentences: list[tuple[str, list[bytes], str]] = []
        self._default_response_ended = False
        self._default_tts_ended = asyncio.Event()
        self._tts_expectation = TtsExpectation()
        self._answer_parts: list[str] = []
        self._sentence_index = 0
        self._llm_started = False
        self._turn_active = False
        self._late_audio_chunks = 0
        self._late_audio_bytes = 0
        self._late_asr_events = 0
        self._transport_lock = asyncio.Lock()
        self._recycle_transport_reason = ""
        self._voice_settings: OmniSessionSettings | None = None
        self._voice_profile_service = None
        self._persona_settings = None
        self._persona_service = None
        self.rag_intent_router = DialogIntentRouter(
            knowledge_service_factory=lambda: get_knowledge_service(self.tenant_id),
            min_score=REALTIME_DIALOG_RAG_MIN_SCORE,
            probe_knowledge=True,
            probe_top_k=REALTIME_DIALOG_RAG_TOP_K,
            intent_embedding_enabled=DIALOG_CHAT_INTENT_EMBEDDING_ENABLED,
            intent_embedding_min_score=DIALOG_CHAT_INTENT_EMBEDDING_MIN_SCORE,
            default_company_min_score=DIALOG_CHAT_DEFAULT_COMPANY_RAG_MIN_SCORE,
        )
        self.person_context_intent_router = PersonContextIntentRouter()

    @property
    def supports_multiple_turns(self) -> bool:
        return True

    @property
    def is_turn_finished(self) -> bool:
        return self._finished.is_set()

    def _on_person_memory_snapshot_changed(self) -> None:
        if not self._started:
            return
        self._recycle_transport_reason = "person_memory_changed"
        logger.info(
            "Omni 人物长期记忆变化，下一轮重建上游会话: conversation=%s person=%s chars=%d",
            self.conversation_id,
            self.person_id or "(anonymous)",
            len(self._person_memory_prompt),
        )

    async def prepare_next_turn(self) -> None:
        if self._turn_active and not self._finished.is_set():
            raise VoicePipelineError("previous Omni turn is still active")
        if self._started and self._voice_settings is not None:
            latest_settings = await self._resolve_voice_settings()
            if latest_settings != self._voice_settings:
                self._recycle_transport_reason = "voice_profile_changed"
                logger.info(
                    "Omni 租户音色版本变化，下一轮重建上游: conversation=%s "
                    "tenant=%s old_version=%s new_version=%s old_clone=%s new_clone=%s",
                    self.conversation_id,
                    self.tenant_id,
                    self._voice_settings.profile_version,
                    latest_settings.profile_version,
                    self._voice_settings.clone_enabled,
                    latest_settings.clone_enabled,
                )
        if self._started and self._persona_settings is not None:
            latest_persona = await self._resolve_persona_settings()
            if latest_persona != self._persona_settings:
                self._recycle_transport_reason = "avatar_persona_changed"
                logger.info(
                    "Omni 租户数字人人设变化，下一轮重建上游: conversation=%s "
                    "tenant=%s old_version=%s new_version=%s old_name=%s new_name=%s "
                    "old_prompt_hash=%s new_prompt_hash=%s",
                    self.conversation_id,
                    self.tenant_id,
                    getattr(self._persona_settings, "version", 0),
                    getattr(latest_persona, "version", 0),
                    getattr(self._persona_settings, "assistant_name", ""),
                    getattr(latest_persona, "assistant_name", ""),
                    self._persona_prompt_hash(self._persona_settings),
                    self._persona_prompt_hash(latest_persona),
                )
        recycle_reason = self._recycle_transport_reason
        if REALTIME_DIALOG_DYNAMIC_NO_CACHE and self._started and not recycle_reason:
            recycle_reason = "dynamic_no_cache"
        if recycle_reason:
            await self._recycle_transport(recycle_reason)
            self._recycle_transport_reason = ""
        self._reset_turn_state()
        self._turn_active = True
        if recycle_reason:
            await self._connect_transport()
        logger.debug("Omni 已准备下一轮: conversation=%s", self.conversation_id)

    async def start(self) -> None:
        if self._started:
            return
        await self._connect_transport()

    async def _connect_transport(self) -> None:
        async with self._transport_lock:
            if self._started and self.transport is not None:
                return
            settings = await self._resolve_voice_settings()
            self._voice_settings = settings
            self._persona_settings = await self._resolve_persona_settings()
            self._validate_settings(settings)
            config = VolcRealtimeDialogConfig(
                app_id=REALTIME_DIALOG_APP_ID,
                app_key=REALTIME_DIALOG_APP_KEY,
                access_key=REALTIME_DIALOG_ACCESS_KEY,
                base_url=REALTIME_DIALOG_BASE_URL,
                resource_id=settings.realtime_resource_id,
                ping_interval_seconds=max(5.0, REALTIME_DIALOG_PING_INTERVAL_SECONDS),
                ping_timeout_seconds=max(3.0, REALTIME_DIALOG_PING_TIMEOUT_SECONDS),
                close_timeout_seconds=max(1.0, REALTIME_DIALOG_CLOSE_TIMEOUT_SECONDS),
            )
            transport = VolcRealtimeDialogClient(
                config,
                start_session_payload=self._build_start_session_payload(),
            )
            try:
                await transport.connect()
            except Exception:
                if not settings.clone_enabled:
                    raise
                logger.exception(
                    "Omni 克隆音色连接失败，单次切换租户默认音色: "
                    "conversation=%s tenant=%s speaker=%s version=%s",
                    self.conversation_id,
                    self.tenant_id,
                    mask_speaker_id(settings.speaker_id),
                    settings.profile_version,
                )
                try:
                    await transport.close()
                except Exception:
                    pass
                settings = replace(
                    settings,
                    speaker_id=settings.fallback_speaker_id,
                    tts_2_0_model="",
                    speaking_style="",
                    clone_enabled=False,
                )
                self._voice_settings = settings
                transport = VolcRealtimeDialogClient(
                    config,
                    start_session_payload=self._build_start_session_payload(),
                )
                await transport.connect()
            self.transport = transport
            self._started = True
            self._receive_task = asyncio.create_task(
                self._receive_loop(transport),
                name=f"omni-receive-{self.conversation_id}",
            )
            await self._send(
                {
                    "type": "ready",
                    "backend": "omni",
                    "serverVad": True,
                    "persistent": True,
                    "endSmoothWindowMs": self._end_smooth_window_ms(),
                }
            )
            persona = self._persona_settings
            logger.info(
                "浏览器 Omni 语音后端已就绪: conversation=%s tenant=%s model=%s "
                "speaker=%s clone=%s profile_version=%s rag=%s "
                "persona_version=%s persona_name=%s persona_customized=%s "
                "persona_system_role_chars=%s persona_speaking_style_chars=%s "
                "persona_prompt_hash=%s "
                "asr_final_timeout=%.1fs empty_asr_timeout=%.1fs "
                "rag_first_audio_timeout=%.1fs rag_completion_timeout=%.1fs keepalive=%.0fs",
                self.conversation_id,
                self.tenant_id,
                settings.model,
                mask_speaker_id(settings.speaker_id),
                settings.clone_enabled,
                settings.profile_version,
                REALTIME_DIALOG_RAG_ENABLED,
                getattr(persona, "version", 0) if persona is not None else 0,
                getattr(persona, "assistant_name", "") if persona is not None else "",
                getattr(persona, "customized", False) if persona is not None else False,
                len(str(getattr(persona, "system_role", "") or "")) if persona is not None else 0,
                len(str(getattr(persona, "speaking_style", "") or "")) if persona is not None else 0,
                self._persona_prompt_hash(persona),
                REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS,
                REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS,
                REALTIME_DIALOG_RAG_FIRST_AUDIO_TIMEOUT_SECONDS,
                REALTIME_DIALOG_RAG_COMPLETION_TIMEOUT_SECONDS,
                config.ping_interval_seconds,
            )

    @staticmethod
    def _persona_prompt_hash(persona: Any | None) -> str:
        if persona is None:
            return ""
        system_role = str(getattr(persona, "system_role", "") or "")
        speaking_style = str(getattr(persona, "speaking_style", "") or "")
        if not system_role and not speaking_style:
            return ""
        value = f"{system_role}\n---speaking_style---\n{speaking_style}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

    async def _resolve_voice_settings(self) -> OmniSessionSettings:
        if self._voice_profile_service is None:
            self._voice_profile_service = get_tenant_voice_profile_service()
        return await asyncio.to_thread(
            self._voice_profile_service.resolve,
            self.tenant_id,
        )

    async def _resolve_persona_settings(self):
        if self._persona_service is None:
            self._persona_service = get_tenant_avatar_persona_service()
        return await asyncio.to_thread(
            self._persona_service.resolve,
            self.tenant_id,
        )

    async def send_audio(self, audio: bytes) -> None:
        if not audio:
            return
        if self._finished.is_set() or not self._turn_active:
            await self.prepare_next_turn()
        if self._input_ended:
            self._late_audio_chunks += 1
            self._late_audio_bytes += len(audio)
            if self._late_audio_chunks == 1 or self._late_audio_chunks % 25 == 0:
                logger.warning(
                    "Omni 丢弃服务端判停后的迟到音频: conversation=%s tenant=%s chunks=%s bytes=%s state=%s",
                    self.conversation_id,
                    self.tenant_id,
                    self._late_audio_chunks,
                    self._late_audio_bytes,
                    self._arbitration_state,
                )
            return
        if not self._started or self.transport is None:
            await self._reconnect_transport()
        if self.transport is None:
            raise VoicePipelineError("Omni transport is unavailable")
        transport = self.transport
        try:
            await transport.send_audio(audio)
        except Exception as exc:
            logger.warning(
                "Omni 音频发送失败，准备重连: conversation=%s error=%s",
                self.conversation_id,
                exc,
            )
            if self.transport is transport:
                self.transport = None
                self._started = False
            try:
                await transport.close()
            except Exception:
                pass
            await self._reconnect_transport()
            if self.transport is None:
                raise VoicePipelineError("Omni transport unavailable after reconnect")
            await self.transport.send_audio(audio)

    async def _reconnect_transport(self) -> None:
        last_error: Exception | None = None
        for attempt, delay in enumerate((0.0, 0.5, 1.0, 2.0, 5.0), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._connect_transport()
                logger.info(
                    "Omni 物理连接恢复成功: conversation=%s attempt=%d",
                    self.conversation_id,
                    attempt,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Omni 物理连接恢复失败: conversation=%s attempt=%d error=%s",
                    self.conversation_id,
                    attempt,
                    exc,
                )
        raise VoicePipelineError(f"Omni reconnect failed: {last_error}")

    async def _recycle_transport(self, reason: str) -> None:
        """Close an expired upstream generation before another turn can start."""

        transport = self.transport
        receive_task = self._receive_task
        self.transport = None
        self._receive_task = None
        self._started = False
        if (
            receive_task is not None
            and receive_task is not asyncio.current_task()
            and not receive_task.done()
        ):
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.info(
                    "Omni 回收物理连接时接收任务已结束: conversation=%s reason=%s error_type=%s error=%s",
                    self.conversation_id,
                    reason,
                    type(exc).__name__,
                    exc,
                )
        if transport is not None:
            try:
                await transport.close()
            except Exception as exc:
                logger.warning(
                    "Omni 回收物理连接关闭失败: conversation=%s reason=%s error_type=%s error=%s",
                    self.conversation_id,
                    reason,
                    type(exc).__name__,
                    exc,
                )
        logger.info(
            "Omni 上游物理连接已回收: conversation=%s reason=%s",
            self.conversation_id,
            reason,
        )

    async def _invalidate_transport(self, reason: str, *, phase: str) -> None:
        """Interrupt an uncertain upstream lane and recycle it next turn."""

        self._recycle_transport_reason = reason
        transport = self.transport
        if transport is not None:
            try:
                await transport.send_client_interrupt()
            except Exception as exc:
                logger.warning(
                    "Omni 上游中断请求失败: conversation=%s phase=%s reason=%s error_type=%s error=%s",
                    self.conversation_id,
                    phase,
                    reason,
                    type(exc).__name__,
                    exc,
                )
        logger.warning(
            "Omni 上游通道已标记回收: conversation=%s tenant=%s phase=%s reason=%s state=%s recycle_next_turn=true",
            self.conversation_id,
            self.tenant_id,
            phase,
            reason,
            self._arbitration_state,
        )

    async def interrupt(
        self,
        *,
        reason: str = "interrupted",
        played_reply_id: str = "",
        played_ms: int = 0,
        previous_user_text: str = "",
        assistant_text: str = "",
        active_sentence: str = "",
        client_mode: str = "",
    ) -> None:
        """Cancel a live generation and never persist its partial response."""

        route_task = self._route_task
        if (
            route_task is not None
            and route_task is not asyncio.current_task()
            and not route_task.done()
        ):
            route_task.cancel()
            await asyncio.gather(route_task, return_exceptions=True)
        self._recycle_transport_reason = reason
        transport = self.transport
        truncated = False
        if transport is not None and played_reply_id and played_ms > 0:
            try:
                await transport.send_conversation_truncate(
                    played_reply_id,
                    played_ms,
                )
                truncated = True
            except Exception as exc:
                logger.warning(
                    "Omni 播报进度截断失败，将回收物理连接: conversation=%s "
                    "tenant=%s reply=%s played_ms=%s error_type=%s error=%s",
                    self.conversation_id,
                    self.tenant_id,
                    played_reply_id[:12] or "(none)",
                    played_ms,
                    type(exc).__name__,
                    exc,
                )
        self._record_interrupted_context(
            previous_user_text=previous_user_text,
            assistant_text=assistant_text,
            active_sentence=active_sentence,
            played_ms=played_ms,
            client_mode=client_mode,
        )
        self._last_completed_turn = None
        self._pending_default_sentences.clear()
        self._allowed_reply_ids.clear()
        self._allowed_reply_order.clear()
        if not truncated:
            await self._recycle_transport(reason)
        self._turn_active = False
        self._finished.set()
        await self._send_done(reason)
        logger.info(
            "Omni 轮次已被用户抢话终止: conversation=%s tenant=%s "
            "reply=%s played_ms=%s truncated=%s transport_recycled=%s recycle_next_turn=%s",
            self.conversation_id,
            self.tenant_id,
            played_reply_id[:12] or "(none)",
            max(0, int(played_ms)),
            truncated,
            not truncated,
            bool(self._recycle_transport_reason),
        )

    def take_completed_turn(self) -> tuple[str, str] | None:
        """Commit local reconnect context only after browser playback acknowledgement."""

        turn = super().take_completed_turn()
        if turn is not None:
            self._append_local_context(turn[0], turn[1])
        return turn

    async def _expire_external_generation(self, reason: str) -> None:
        """Invalidate an uncertain external generation and recycle it next turn."""

        await self._invalidate_transport(reason, phase="rag_external")

    async def _interrupt_default_generation_for_external_rag(
        self,
        *,
        payload_chars: int,
        discarded_default: int,
    ) -> None:
        """Actively free the upstream default lane before sending event 502."""

        transport = self.transport
        if transport is None:
            logger.warning(
                "Omni RAG 命中但上游连接不存在，无法中断默认生成: conversation=%s tenant=%s payload_chars=%s discarded_default=%s",
                self.conversation_id,
                self.tenant_id,
                payload_chars,
                discarded_default,
            )
            return
        started_at = time.perf_counter()
        try:
            await transport.send_client_interrupt()
        except Exception as exc:
            self._recycle_transport_reason = "rag_default_interrupt_failed"
            logger.warning(
                "Omni RAG 前中断默认生成失败: conversation=%s tenant=%s payload_chars=%s discarded_default=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                payload_chars,
                discarded_default,
                type(exc).__name__,
                exc,
            )
            raise
        self._recycle_transport_reason = (
            self._recycle_transport_reason or "rag_default_interrupted"
        )
        self._default_response_ended = True
        self._default_tts_ended.set()
        logger.info(
            "Omni RAG 命中后已主动中断默认生成: conversation=%s tenant=%s interrupt_ms=%.0f payload_chars=%s discarded_default=%s recycle_next_turn=true",
            self.conversation_id,
            self.tenant_id,
            (time.perf_counter() - started_at) * 1000,
            payload_chars,
            discarded_default,
        )

    async def _interrupt_default_generation_for_chat_text(
        self,
        *,
        reason: str,
        payload_chars: int,
    ) -> None:
        default_seen = (
            TTS_TYPE_DEFAULT in self._response_types_seen
            or self._current_tts_type == TTS_TYPE_DEFAULT
            or bool(self._pending_default_sentences)
        )
        if not default_seen or self._default_response_ended:
            return
        transport = self.transport
        if transport is None:
            return
        started_at = time.perf_counter()
        try:
            await transport.send_client_interrupt()
        except Exception as exc:
            self._recycle_transport_reason = f"{reason}_default_interrupt_failed"
            logger.warning(
                "Omni 确定性回答前中断默认生成失败: conversation=%s tenant=%s reason=%s payload_chars=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                reason,
                payload_chars,
                type(exc).__name__,
                exc,
            )
            raise
        self._recycle_transport_reason = (
            self._recycle_transport_reason or f"{reason}_default_interrupted"
        )
        self._default_response_ended = True
        self._default_tts_ended.set()
        logger.info(
            "Omni 确定性回答前已主动中断默认生成: conversation=%s tenant=%s reason=%s interrupt_ms=%.0f payload_chars=%s recycle_next_turn=true",
            self.conversation_id,
            self.tenant_id,
            reason,
            (time.perf_counter() - started_at) * 1000,
            payload_chars,
        )

    async def _before_dialog_silence_control_response(
        self,
        result: DialogSilenceResult,
    ) -> None:
        if result.action not in {ACTION_MUTE, ACTION_SUPPRESS, ACTION_WAKE}:
            return
        transport = self.transport
        self._pending_default_sentences.clear()
        self._pending_response_text = ""
        if self._current_tts_type == TTS_TYPE_DEFAULT:
            self._current_tts_type = ""
            self._current_tts_text = ""
            self._current_reply_id = ""
            self._current_audio_chunks = []
        if transport is None:
            logger.info(
                "Omni 静音控制无上游连接可中断: conversation=%s tenant=%s action=%s",
                self.conversation_id,
                self.tenant_id,
                result.action,
            )
            return
        started_at = time.perf_counter()
        try:
            await transport.send_client_interrupt()
        except Exception as exc:
            self._recycle_transport_reason = (
                f"dialog_silence_{result.action}_interrupt_failed"
            )
            logger.warning(
                "Omni 静音控制中断默认生成失败: conversation=%s tenant=%s action=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                result.action,
                type(exc).__name__,
                exc,
            )
            raise
        self._recycle_transport_reason = (
            self._recycle_transport_reason
            or f"dialog_silence_{result.action}_interrupted"
        )
        self._default_response_ended = True
        self._default_tts_ended.set()
        logger.info(
            "Omni 静音控制已中断默认生成: conversation=%s tenant=%s action=%s interrupt_ms=%.0f recycle_next_turn=true",
            self.conversation_id,
            self.tenant_id,
            result.action,
            (time.perf_counter() - started_at) * 1000,
        )

    async def finish_audio(self) -> None:
        """Client-side VAD is only a failsafe; server VAD normally finishes first."""
        if not self._started:
            await self._send_done("empty_asr")
            self._finished.set()
            return
        client_stop_started_at = time.perf_counter()
        asr_deadline = (
            client_stop_started_at
            + max(0.05, REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS)
        )
        empty_asr_deadline = (
            client_stop_started_at
            + max(0.05, REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS)
        )
        if not self._input_ended and self.transport is not None:
            # Feed enough silence for server VAD when a manual stop happens before
            # end_smooth_window_ms. Each packet is 20ms of 16kHz int16 mono PCM.
            silence_packets = max(1, self._end_smooth_window_ms() // 20 + 5)
            logger.info(
                "Omni 收到客户端结束兜底: conversation=%s silence_packets=%s",
                self.conversation_id,
                silence_packets,
            )
            for _ in range(silence_packets):
                if self._input_ended:
                    break
                await self.transport.send_audio(b"\x00" * 640)
                await asyncio.sleep(0.02)
        if not self._input_ended and not self._finished.is_set():
            no_partial_text = not self._last_user_text.strip()
            effective_deadline = (
                min(asr_deadline, empty_asr_deadline)
                if no_partial_text
                else asr_deadline
            )
            remaining_seconds = max(0.0, effective_deadline - time.perf_counter())
            asr_finalized = await self._wait_for_asr_finalization(
                remaining_seconds
            )
            if not asr_finalized:
                if self._finished.is_set():
                    return
                elapsed_seconds = time.perf_counter() - client_stop_started_at
                if no_partial_text:
                    logger.info(
                        "Omni 空识别未收到最终判停，快速恢复监听: conversation=%s tenant=%s empty_timeout=%.1fs elapsed=%.1fs",
                        self.conversation_id,
                        self.tenant_id,
                        REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS,
                        elapsed_seconds,
                    )
                    self._input_ended = True
                    await self._invalidate_transport(
                        "empty_asr_final_timeout",
                        phase="asr_final_empty",
                    )
                    await self._recycle_transport("empty_asr_final_timeout")
                    await self._complete_turn(reason="empty_asr", send_llm_end=False)
                    return
                logger.error(
                    "Omni 客户端停顿后未收到最终识别，立即回收连接: conversation=%s tenant=%s timeout=%.1fs elapsed=%.1fs partial_chars=%d",
                    self.conversation_id,
                    self.tenant_id,
                    REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS,
                    elapsed_seconds,
                    len(self._last_user_text.strip()),
                )
                self._input_ended = True
                await self._invalidate_transport(
                    "asr_final_timeout",
                    phase="asr_final",
                )
                await self._recycle_transport("asr_final_timeout")
                await self._fail_turn(
                    "这次没有识别完整，请再说一次。",
                    recoverable=True,
                    code="asr_final_timeout",
                    reason="asr_final_timeout",
                )
                return
        if self._finished.is_set():
            return
        try:
            await asyncio.wait_for(
                self._finished.wait(),
                timeout=max(
                    15.0,
                    REALTIME_DIALOG_RAG_FIRST_AUDIO_TIMEOUT_SECONDS
                    + REALTIME_DIALOG_RAG_COMPLETION_TIMEOUT_SECONDS
                    + 8.0,
                ),
            )
        except asyncio.TimeoutError:
            logger.error(
                "Omni 回答阶段等待完成超时，回收连接: conversation=%s tenant=%s state=%s",
                self.conversation_id,
                self.tenant_id,
                self._arbitration_state,
            )
            await self._invalidate_transport(
                "turn_completion_timeout",
                phase="completion",
            )
            await self._recycle_transport("turn_completion_timeout")
            await self._fail_turn(
                "回答等待超时，请重新说一次。",
                recoverable=True,
                code="turn_completion_timeout",
                reason="turn_completion_timeout",
            )

    async def _wait_for_asr_finalization(self, timeout_seconds: float) -> bool:
        """Wait only for ASR/server-VAD, independently from RAG completion."""

        if self._input_ended or self._asr_ended.is_set():
            return True
        if self._finished.is_set() or timeout_seconds <= 0:
            return False
        asr_ended = asyncio.create_task(self._asr_ended.wait())
        turn_finished = asyncio.create_task(self._finished.wait())
        wait_tasks = {asr_ended, turn_finished}
        try:
            completed, _ = await asyncio.wait(
                wait_tasks,
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not completed:
                return False
            return self._asr_ended.is_set() or self._input_ended
        finally:
            for task in wait_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*wait_tasks, return_exceptions=True)

    async def close(self) -> None:
        if self._route_task is not None and not self._route_task.done():
            self._route_task.cancel()
            try:
                await self._route_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self._receive_task is not None and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.transport is not None:
            await self.transport.close()
        self.transport = None
        self._started = False
        self._closed = True
        self._finished.set()
        logger.info(
            "浏览器 Omni 会话已关闭: conversation=%s answer_chars=%s",
            self.conversation_id,
            len(self._final_answer_text()),
        )

    async def _send(self, payload: dict) -> bool:
        async with self._browser_send_lock:
            return await super()._send(payload)

    async def _receive_loop(self, transport: VolcRealtimeDialogClient) -> None:
        try:
            while not self._closed and self.transport is transport:
                response = await transport.receive()
                await self._handle_omni_response(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                if self._is_idle_timeout(exc) and not self._last_user_text.strip():
                    logger.info(
                        "Omni 空闲物理会话被上游释放: conversation=%s reason=audio_idle_timeout",
                        self.conversation_id,
                    )
                    if self._turn_active and not self._finished.is_set():
                        await self._complete_turn(
                            reason="empty_asr",
                            send_llm_end=False,
                        )
                else:
                    logger.exception("Omni 接收循环异常: %s", exc)
                    if self._turn_active and not self._finished.is_set():
                        await self._fail_turn(str(exc), recoverable=True)
                if self.transport is transport:
                    self.transport = None
                    self._started = False
                try:
                    await transport.close()
                except Exception:
                    pass

    async def _handle_omni_response(self, response: dict[str, Any]) -> None:
        message_type = response.get("message_type")
        event = response.get("event")
        payload = response.get("payload_msg")

        if message_type == "SERVER_ACK" and isinstance(payload, bytes):
            if self._current_tts_type:
                self._current_audio_chunks.append(payload)
                self._tts_expectation.record_audio(
                    self._current_tts_type,
                    len(payload),
                )
            return

        if event == 451:
            if self._input_ended:
                self._late_asr_events += 1
                if self._late_asr_events == 1:
                    logger.warning(
                        "Omni 忽略服务端判停后的迟到 ASR: conversation=%s tenant=%s state=%s",
                        self.conversation_id,
                        self.tenant_id,
                        self._arbitration_state,
                    )
                return
            text, is_interim = self._extract_asr_result(payload)
            if text:
                self._last_user_text = text
                await self._send(
                    {"type": "asr_partial", "text": text, "final": not is_interim}
                )
            return

        if event == 459:
            await self._on_asr_ended()
            return

        if event == 350:
            self._current_tts_type = self._extract_nested_string(
                payload,
                "tts_type",
            )
            self._current_reply_id = self._extract_nested_string(
                payload,
                "reply_id",
            )
            self._current_tts_text = (
                self._extract_assistant_text(payload) or self._pending_response_text
            )
            if self._current_reply_id:
                self._current_tts_text = (
                    self._current_tts_text
                    or self._reply_texts.get(self._current_reply_id, "")
                )
            self._current_tts_text = self._resolve_expected_tts_text(
                self._current_tts_type,
                self._current_tts_text,
                phase="sentence_start",
            )
            self._pending_response_text = ""
            self._current_audio_chunks = []
            if self._current_tts_type:
                self._response_types_seen.add(self._current_tts_type)
            if self._current_tts_type == TTS_TYPE_AUDIT:
                self._response_mode = "audit"
                self._pending_default_sentences.clear()
            if (
                self._current_tts_type != TTS_TYPE_CHAT_TEXT
                and self._tts_type_allowed(self._current_tts_type)
                and self._current_reply_id
                and not (
                    self._current_tts_type == TTS_TYPE_EXTERNAL_RAG
                    and self._arbitration_state == ARBITRATION_EXTERNAL_PENDING
                )
            ):
                self._allow_reply(self._current_reply_id)
                await self._emit_reply_text(
                    self._current_reply_id,
                    self._current_tts_text,
                )
            logger.info(
                "Omni 句子开始: conversation=%s type=%s reply=%s chars=%s",
                self.conversation_id,
                self._current_tts_type or "unknown",
                self._current_reply_id or "(missing)",
                len(self._current_tts_text),
            )
            return

        if event == 550:
            content = self._extract_assistant_text(payload)
            reply_id = self._extract_nested_string(payload, "reply_id")
            if content:
                if reply_id:
                    content = self._merge_stream_text(
                        self._reply_texts.get(reply_id, ""),
                        content,
                    )
                    self._reply_texts[reply_id] = content
                if self._current_tts_type and (
                    not reply_id or reply_id == self._current_reply_id
                ):
                    self._current_tts_text = self._merge_stream_text(
                        self._current_tts_text,
                        content,
                    )
                else:
                    self._pending_response_text = self._merge_stream_text(
                        self._pending_response_text,
                        content,
                    )
                if reply_id in self._allowed_reply_ids:
                    await self._emit_reply_text(reply_id, content)
                logger.debug(
                    "Omni 文本响应: conversation=%s reply=%s chars=%s allowed=%s current_type=%s",
                    self.conversation_id,
                    reply_id or "(missing)",
                    len(content),
                    reply_id in self._allowed_reply_ids,
                    self._current_tts_type or "(none)",
                )
            elif self._current_tts_type == TTS_TYPE_EXTERNAL_RAG:
                logger.debug(
                    "Omni 外部 RAG 文本事件为空: conversation=%s payload_keys=%s",
                    self.conversation_id,
                    self._payload_keys(payload),
                )
            return

        if event == 351:
            await self._finish_current_sentence()
            return

        if event == 359:
            await self._on_tts_ended(payload)
            return

        if event == 599:
            status = self._extract_string(payload, "status_code")
            message = self._extract_string(payload, "message")
            raise VolcRealtimeDialogError(
                f"Omni dialog error status={status or 'unknown'} message={message or payload}"
            )

        if event == 154:
            logger.info("Omni 用量: conversation=%s usage=%s", self.conversation_id, payload)
        elif event not in {450, 550, 559}:
            logger.debug(
                "Omni 服务端事件: conversation=%s event=%s payload=%s",
                self.conversation_id,
                event,
                payload,
            )

    async def _on_asr_ended(self) -> None:
        if self._input_ended:
            return
        self._input_ended = True
        self._asr_ended.set()
        user_text = self._last_user_text.strip()
        logger.info(
            "Omni 服务端判停: conversation=%s chars=%s text=%s",
            self.conversation_id,
            len(user_text),
            user_text,
        )
        if not user_text:
            await self._complete_turn(reason="empty_asr", send_llm_end=False)
            return
        await self._send(
            {
                "type": "asr_final",
                "text": user_text,
                "serverVad": True,
                "backend": "omni",
            }
        )
        self._llm_started = True
        await self._send({"type": "llm_start", "backend": "omni"})
        self._route_task = asyncio.create_task(
            self._route_completed_query(user_text),
            name=f"omni-route-{self.conversation_id}",
        )

    async def _route_completed_query(self, user_text: str) -> None:
        route_started_at = time.perf_counter()
        phase = "routing"
        try:
            silence = await self._handle_dialog_silence_control(user_text)
            if silence.handled:
                await self._complete_turn(
                    reason=silence.reason,
                    send_llm_end=False,
                )
                return
            route_source_text = silence.route_text or user_text
            wake = await self._handle_assistant_wake_name(route_source_text)
            if wake.wake_only:
                await self._complete_turn(send_llm_end=False)
                return
            route_text = wake.command_text
            if await self._handle_person_memory_command(route_text):
                await self._complete_turn(send_llm_end=False)
                return
            person_reply = self.person_context_intent_router.route(
                route_text,
                person_name=self.person_name,
                identity_verified=self.person_identity_verified,
                context=self._person_memory_context or self._context,
                dated_recall=await self._load_dated_conversation_recall(
                    route_text
                ),
            )
            if person_reply is not None:
                logger.info(
                    "Omni 人物上下文意图命中: conversation=%s intent=%s verified=%s clarification=%s person=%s context_messages=%s",
                    self.conversation_id,
                    person_reply.intent,
                    person_reply.identity_verified,
                    person_reply.needs_clarification,
                    self.person_name or "(unknown)",
                    person_reply.source_messages,
                )
                required_facts = list(person_reply.required_facts or (person_reply.text,))
                external_rag = self._build_person_context_external_rag(
                    route_text,
                    person_reply,
                    required_facts,
                    constraints=[
                        *person_reply.constraints,
                        "先理解用户问题再组织回答，不要把事实材料当成逐字稿念出来。",
                    ],
                )
                await self._send_person_context_external_response(
                    person_reply,
                    external_rag,
                )
                return

            if await self._handle_voice_action(route_text):
                logger.info(
                    "Omni 业务动作处理完成: conversation=%s route_ms=%.0f",
                    self.conversation_id,
                    (time.perf_counter() - route_started_at) * 1000,
                )
                await self._complete_turn(send_llm_end=False)
                return

            persona = self._persona_settings or await self._resolve_persona_settings()
            quick_scene = classify_local_quick_reply_scene(route_text, persona=persona)
            if quick_scene:
                logger.info(
                    "Omni 本地快速回复转模型生成: conversation=%s scene=%s query=%s canonical=%s",
                    self.conversation_id,
                    quick_scene.scene,
                    route_text,
                    quick_scene.canonical_text,
                )
                spoken = await self._generate_scene_reply(
                    quick_scene.canonical_text,
                    scene=quick_scene.scene,
                    user_text=route_text,
                    required_facts=[quick_scene.canonical_text],
                    response_goal=quick_scene.response_goal,
                    constraints=list(quick_scene.constraints),
                )
                await self._send({"type": "llm_delta", "text": spoken})
                await self._synthesize_sentence(spoken, 1)
                await self._complete_turn()
                return

            external_rag = ""
            rag_results: list[Any] | None = None
            if REALTIME_DIALOG_RAG_ENABLED:
                phase = "intent_route"
                intent_started_at = time.perf_counter()
                intent_route = await asyncio.to_thread(
                    self.rag_intent_router.route,
                    route_text,
                )
                logger.info(
                    "Omni RAG 意图路由: conversation=%s route=%s reason=%s confidence=%.3f probe_min=%.3f route_ms=%.0f query=%s",
                    self.conversation_id,
                    intent_route.route,
                    intent_route.reason,
                    intent_route.confidence,
                    intent_route.knowledge_min_score,
                    (time.perf_counter() - intent_started_at) * 1000,
                    route_text,
                )
                if not intent_route.use_knowledge:
                    logger.info(
                        "Omni 闲聊严格绕过企业知识 RAG: conversation=%s reason=%s memory_chars=%d",
                        self.conversation_id,
                        intent_route.reason,
                        len(self._person_memory_prompt),
                    )
                    await self._release_default_response(
                        reason=intent_route.reason,
                    )
                    return
                else:
                    phase = "rag_build"
                    rag_results = (
                        intent_route.results
                        if intent_route.knowledge_probed
                        else None
                    )
                    external_rag = await asyncio.to_thread(
                        self._build_external_rag,
                        route_text,
                        rag_results,
                    )
            if not external_rag:
                fallback_reason = (
                    "rag_miss" if REALTIME_DIALOG_RAG_ENABLED else "rag_disabled"
                )
                logger.info(
                    "Omni 使用模型默认回答: conversation=%s reason=%s route_ms=%.0f",
                    self.conversation_id,
                    fallback_reason,
                    (time.perf_counter() - route_started_at) * 1000,
                )
                await self._release_default_response(reason=fallback_reason)
                return

            phase = "rag_wait_default"
            default_wait_seconds = await self._wait_for_default_tts_end_for_external_rag(
                payload_chars=len(external_rag),
            )
            self._response_mode = TTS_TYPE_EXTERNAL_RAG
            self._set_arbitration_state(
                ARBITRATION_EXTERNAL_PENDING,
                reason="rag_selected",
            )
            phase = "rag_external"
            logger.info(
                "Omni 发送外部 RAG 事件: conversation=%s tenant=%s payload_chars=%s pending_default=%s default_wait_ms=%.0f",
                self.conversation_id,
                self.tenant_id,
                len(external_rag),
                len(self._pending_default_sentences),
                default_wait_seconds * 1000,
            )
            duration = await self._request_external_rag_response(
                lambda: self._require_transport().send_external_rag(external_rag),
            )
            if self._arbitration_state != ARBITRATION_EXTERNAL_COMMITTED:
                reason = "rag_no_external_audio"
                logger.warning(
                    "Omni 外部 RAG 完成但未提交音频: conversation=%s tenant=%s rag_chars=%s state=%s pending_default=%s",
                    self.conversation_id,
                    self.tenant_id,
                    len(external_rag),
                    self._arbitration_state,
                    len(self._pending_default_sentences),
                )
                await self._expire_external_generation(reason)
                if not self._finished.is_set():
                    released = await self._release_default_response(reason=reason)
                    if not released and not self._finished.is_set():
                        await self._complete_turn(reason=reason)
                return
            logger.info(
                "Omni 外部 RAG 回答完成: conversation=%s rag_chars=%s answer_chars=%s audio_seconds=%.2f total_ms=%.0f state=%s",
                self.conversation_id,
                len(external_rag),
                len(self._final_answer_text()),
                duration,
                (time.perf_counter() - route_started_at) * 1000,
                self._arbitration_state,
            )
            await self._complete_turn()
        except asyncio.CancelledError:
            raise
        except ExternalRagTimeout as exc:
            reason = (
                "rag_first_audio_timeout"
                if exc.stage == "first_audio"
                else "rag_completion_timeout"
            )
            logger.error(
                "Omni 外部 RAG 分级等待超时: conversation=%s tenant=%s stage=%s timeout=%.1fs state=%s pending_default=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                exc.stage,
                exc.timeout_seconds,
                self._arbitration_state,
                len(self._pending_default_sentences),
                type(exc).__name__,
                exc,
            )
            await self._expire_external_generation(reason)
            if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
                if not self._finished.is_set():
                    await self._complete_turn(reason=reason)
            elif not self._finished.is_set():
                released = await self._release_default_response(reason=reason)
                if not released and not self._finished.is_set():
                    await self._complete_turn(reason=reason)
        except TimeoutError as exc:
            reason = (
                "rag_tts_timeout"
                if phase == "rag_external"
                else "route_timeout"
            )
            logger.error(
                "Omni 查询分流超时: conversation=%s tenant=%s phase=%s state=%s pending_default=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                phase,
                self._arbitration_state,
                len(self._pending_default_sentences),
                type(exc).__name__,
                exc,
            )
            if phase == "rag_external":
                await self._expire_external_generation(reason)
                if not self._finished.is_set():
                    if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
                        await self._complete_turn(reason=reason)
                    else:
                        released = await self._release_default_response(reason=reason)
                        if not released and not self._finished.is_set():
                            await self._complete_turn(reason=reason)
                return
            if not self._finished.is_set():
                released = await self._release_default_response(reason=reason)
                if not released and not self._finished.is_set():
                    await self._complete_turn(reason=reason)
        except Exception as exc:
            if phase in {"intent_route", "rag_build"}:
                reason = "rag_search_error"
            elif phase in {"rag_wait_default", "rag_external"}:
                reason = "rag_tts_error"
            else:
                reason = "route_error"
            logger.exception(
                "Omni 查询分流失败: conversation=%s tenant=%s phase=%s state=%s pending_default=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                phase,
                self._arbitration_state,
                len(self._pending_default_sentences),
                type(exc).__name__,
                exc,
            )
            if phase == "rag_external":
                await self._expire_external_generation(reason)
            if not self._finished.is_set():
                if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
                    await self._complete_turn(reason=reason)
                else:
                    released = await self._release_default_response(reason=reason)
                    if not released and not self._finished.is_set():
                        await self._complete_turn(reason=reason)

    async def _load_dated_conversation_recall(
        self,
        query_text: str,
    ) -> dict | None:
        offset = conversation_recall_day_offset(query_text)
        if offset is None:
            return None
        target_date = (
            datetime.now(timezone(timedelta(hours=8))).date()
            + timedelta(days=offset)
        ).isoformat()
        target_label = conversation_recall_day_label(offset, target_date)
        if not self.person_memory_read_allowed or not self.person_id:
            return {
                "target_date": target_date,
                "target_label": target_label,
                "summary": "",
                "turns": (),
                "source_turn_count": 0,
            }
        try:
            recall = await asyncio.to_thread(
                get_person_memory_service().recall_daily_conversation,
                person_id=self.person_id,
                memory_read_allowed=self.person_memory_read_allowed,
                target_date=target_date,
                target_label=target_label,
            )
        except Exception:
            logger.exception(
                "Omni 日期对话回忆读取异常: conversation=%s person=%s target_date=%s",
                self.conversation_id,
                self.person_id,
                target_date,
            )
            return {
                "target_date": target_date,
                "target_label": target_label,
                "summary": "",
                "turns": (),
                "source_turn_count": 0,
            }
        logger.info(
            "Omni 日期对话回忆已读取: conversation=%s person=%s target_date=%s label=%s summary_chars=%s turns=%s",
            self.conversation_id,
            self.person_id,
            target_date,
            target_label,
            len(str(recall.get("summary") or "")),
            len(recall.get("turns") or ()),
        )
        return recall

    async def _synthesize_sentence(self, text: str, index: int) -> float:
        text = normalize_tts_text(text)
        if not text:
            return 0.0
        self._response_mode = TTS_TYPE_CHAT_TEXT
        self._pending_default_sentences.clear()
        if text not in self._answer_parts:
            self._answer_parts.append(text)
        return await self._request_tts_response(
            TTS_TYPE_CHAT_TEXT,
            lambda: self._require_transport().send_chat_tts_text(text),
            expected_text=text,
        )

    async def _wait_for_default_tts_end_for_external_rag(
        self,
        *,
        payload_chars: int,
    ) -> float:
        """Serialize 502 after the model's default TTS lane has settled."""

        if self._default_response_ended:
            logger.info(
                "Omni RAG 串行等待跳过: conversation=%s default_already_ended=true payload_chars=%s pending_default=%s",
                self.conversation_id,
                payload_chars,
                len(self._pending_default_sentences),
            )
            return 0.0
        default_seen = (
            TTS_TYPE_DEFAULT in self._response_types_seen
            or self._current_tts_type == TTS_TYPE_DEFAULT
            or bool(self._pending_default_sentences)
        )
        if not default_seen:
            logger.info(
                "Omni RAG 串行等待跳过: conversation=%s default_seen=false payload_chars=%s pending_default=%s",
                self.conversation_id,
                payload_chars,
                len(self._pending_default_sentences),
            )
            return 0.0

        started_at = time.perf_counter()
        try:
            await asyncio.wait_for(
                self._default_tts_ended.wait(),
                timeout=REALTIME_DIALOG_RAG_SERIAL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Omni RAG 等待默认 TTS 结束超时: conversation=%s timeout=%.1fs payload_chars=%s pending_default=%s",
                self.conversation_id,
                REALTIME_DIALOG_RAG_SERIAL_TIMEOUT_SECONDS,
                payload_chars,
                len(self._pending_default_sentences),
            )
            raise
        wait_seconds = time.perf_counter() - started_at
        logger.info(
            "Omni RAG 默认 TTS 已结束: conversation=%s wait_ms=%.0f payload_chars=%s pending_default=%s",
            self.conversation_id,
            wait_seconds * 1000,
            payload_chars,
            len(self._pending_default_sentences),
        )
        return wait_seconds

    async def _request_tts_response(
        self,
        expected_type: str,
        sender: Callable[[], Awaitable[None]],
        *,
        expected_text: str = "",
        timeout_seconds: float | None = None,
    ) -> float:
        try:
            self._tts_expectation.begin(
                expected_type,
                expected_text=normalize_tts_text(expected_text),
            )
        except TtsExpectationError as exc:
            raise VoicePipelineError(f"Omni {exc}") from exc
        try:
            await sender()
            return await self._tts_expectation.wait_for_completion(
                REALTIME_DIALOG_RAG_COMPLETION_TIMEOUT_SECONDS
                if timeout_seconds is None
                else timeout_seconds,
            )
        finally:
            self._tts_expectation.reset()

    async def _request_external_rag_response(
        self,
        sender: Callable[[], Awaitable[None]],
    ) -> float:
        try:
            self._tts_expectation.begin(TTS_TYPE_EXTERNAL_RAG)
        except TtsExpectationError as exc:
            raise VoicePipelineError(f"Omni {exc}") from exc
        try:
            await sender()
            return await self._tts_expectation.wait_for_external(
                first_audio_timeout_seconds=(
                    REALTIME_DIALOG_RAG_FIRST_AUDIO_TIMEOUT_SECONDS
                ),
                completion_timeout_seconds=(
                    REALTIME_DIALOG_RAG_COMPLETION_TIMEOUT_SECONDS
                ),
            )
        finally:
            self._tts_expectation.reset()

    async def _finish_current_sentence(self) -> None:
        tts_type = self._current_tts_type
        text = self._resolve_expected_tts_text(
            tts_type,
            self._current_tts_text,
            phase="sentence_finish",
        )
        reply_id = self._current_reply_id
        chunks = self._current_audio_chunks
        self._current_tts_type = ""
        self._current_tts_text = ""
        self._current_reply_id = ""
        self._current_audio_chunks = []
        if reply_id:
            text = text or self._reply_texts.get(reply_id, "")
        if not chunks:
            logger.warning(
                "Omni 句子无音频: conversation=%s type=%s chars=%s",
                self.conversation_id,
                tts_type or "unknown",
                len(text),
            )
            return

        if (
            tts_type == TTS_TYPE_DEFAULT
            and self._arbitration_state in PENDING_DEFAULT_STATES
        ):
            self._pending_default_sentences.append((text, chunks, reply_id))
            logger.debug(
                "Omni 暂存默认回答: conversation=%s pending=%s bytes=%s",
                self.conversation_id,
                len(self._pending_default_sentences),
                sum(len(chunk) for chunk in chunks),
            )
            return
        if (
            tts_type == TTS_TYPE_EXTERNAL_RAG
            and self._arbitration_state == ARBITRATION_EXTERNAL_PENDING
        ):
            self._commit_external_response()
        if not self._tts_type_allowed(tts_type):
            logger.info(
                "Omni 丢弃非目标回答: conversation=%s expected=%s actual=%s bytes=%s",
                self.conversation_id,
                self._response_mode,
                tts_type or "unknown",
                sum(len(chunk) for chunk in chunks),
            )
            return
        await self._dispatch_sentence(text, chunks, tts_type, reply_id)
        first_audio_ms = self._tts_expectation.mark_first_audio(tts_type)
        if first_audio_ms is not None and tts_type == TTS_TYPE_EXTERNAL_RAG:
            logger.info(
                "Omni 外部 RAG 首段音频就绪: conversation=%s tenant=%s first_audio_ms=%.0f bytes=%s",
                self.conversation_id,
                self.tenant_id,
                first_audio_ms,
                self._tts_expectation.received_bytes,
            )

    async def _dispatch_sentence(
        self,
        text: str,
        chunks: list[bytes],
        tts_type: str,
        reply_id: str = "",
    ) -> None:
        audio, metadata = assemble_wav_audio(
            chunks,
            sample_rate=REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
        )
        if not audio:
            return
        self._sentence_index += 1
        if text and tts_type != TTS_TYPE_CHAT_TEXT:
            if reply_id:
                self._allow_reply(reply_id)
                await self._emit_reply_text(reply_id, text)
            else:
                self._answer_parts.append(text)
                await self._send({"type": "llm_delta", "text": text})
        await self._send(
            {
                "type": "tts_start",
                "index": self._sentence_index,
                "text": text,
                "mime": "audio/wav",
                "ttsType": tts_type,
                "backend": "omni",
            }
        )
        await self._send(
            {
                "type": "tts_audio",
                "index": self._sentence_index,
                "text": text,
                "mime": "audio/wav",
                "bytes": len(audio),
                "chunkCount": len(chunks),
                "durationMs": metadata.get("duration_ms"),
                "ttsType": tts_type,
                "replyId": reply_id,
                "audio": base64.b64encode(audio).decode("ascii"),
            }
        )
        await self._send({"type": "tts_end", "index": self._sentence_index})
        logger.info(
            "Omni 句子下发浏览器: conversation=%s index=%s type=%s chars=%s chunks=%s bytes=%s duration_ms=%s",
            self.conversation_id,
            self._sentence_index,
            tts_type,
            len(text),
            len(chunks),
            len(audio),
            metadata.get("duration_ms"),
        )

    def _resolve_expected_tts_text(
        self,
        tts_type: str,
        upstream_text: str,
        *,
        phase: str,
    ) -> str:
        """Use requested text as the display truth for deterministic TTS."""

        expected_text = self._tts_expectation.expected_text
        if (
            tts_type != TTS_TYPE_CHAT_TEXT
            or self._tts_expectation.expected_type != TTS_TYPE_CHAT_TEXT
            or not expected_text
        ):
            return upstream_text
        if upstream_text and normalize_tts_text(upstream_text) != expected_text:
            logger.warning(
                "Omni 确定性 TTS 文本不一致，使用请求文本: conversation=%s phase=%s upstream_chars=%d expected_chars=%d",
                self.conversation_id,
                phase,
                len(upstream_text),
                len(expected_text),
            )
        return expected_text

    async def _on_tts_ended(self, payload: Any) -> None:
        ended_types = set(self._response_types_seen)
        self._response_types_seen.clear()
        self._pending_response_text = ""
        if TTS_TYPE_DEFAULT in ended_types:
            self._default_response_ended = True
            self._default_tts_ended.set()
        self._tts_expectation.mark_completed(
            ended_types,
            bytes_per_second=max(1, REALTIME_DIALOG_OUTPUT_SAMPLE_RATE * 2),
        )
        logger.info(
            "Omni 一轮音频结束: conversation=%s types=%s mode=%s pending_default=%s",
            self.conversation_id,
            sorted(ended_types),
            self._response_mode,
            len(self._pending_default_sentences),
        )
        if self._response_mode == "default" and TTS_TYPE_DEFAULT in ended_types:
            await self._complete_turn()
        elif self._response_mode == "audit" and TTS_TYPE_AUDIT in ended_types:
            await self._complete_turn()

    async def _release_default_response(self, *, reason: str = "default") -> bool:
        if self._finished.is_set():
            logger.debug(
                "Omni 轮次已结束，忽略普通回答释放: conversation=%s reason=%s",
                self.conversation_id,
                reason,
            )
            return False
        if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
            logger.warning(
                "Omni 普通回答回退已跳过: conversation=%s tenant=%s reason=%s state=%s",
                self.conversation_id,
                self.tenant_id,
                reason,
                self._arbitration_state,
            )
            return False
        if self._default_fallback_released:
            logger.debug(
                "Omni 普通回答已释放，忽略重复请求: conversation=%s reason=%s",
                self.conversation_id,
                reason,
            )
            return True
        self._default_fallback_released = True
        self._set_arbitration_state(ARBITRATION_DEFAULT, reason=reason)
        self._response_mode = "default"
        pending = list(self._pending_default_sentences)
        self._pending_default_sentences.clear()
        logger.info(
            "Omni 释放普通回答: conversation=%s tenant=%s reason=%s sentences=%s default_ended=%s",
            self.conversation_id,
            self.tenant_id,
            reason,
            len(pending),
            self._default_response_ended,
        )
        if not pending and not self._default_response_ended:
            logger.warning(
                "Omni 普通回答无可释放内容: conversation=%s tenant=%s reason=%s state=%s",
                self.conversation_id,
                self.tenant_id,
                reason,
                self._arbitration_state,
            )
            return False
        for text, chunks, reply_id in pending:
            await self._dispatch_sentence(
                text or self._reply_texts.get(reply_id, ""),
                chunks,
                TTS_TYPE_DEFAULT,
                reply_id,
            )
        if self._default_response_ended:
            await self._complete_turn()
        return True

    def _commit_external_response(self) -> None:
        if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
            return
        if self._arbitration_state != ARBITRATION_EXTERNAL_PENDING:
            logger.warning(
                "Omni 外部 RAG 提交状态异常: conversation=%s tenant=%s state=%s",
                self.conversation_id,
                self.tenant_id,
                self._arbitration_state,
            )
            return
        pending_count = len(self._pending_default_sentences)
        self._pending_default_sentences.clear()
        self._set_arbitration_state(
            ARBITRATION_EXTERNAL_COMMITTED,
            reason="first_external_audio",
        )
        logger.info(
            "Omni 外部 RAG 回答已提交: conversation=%s tenant=%s discarded_default=%s",
            self.conversation_id,
            self.tenant_id,
            pending_count,
        )

    def _set_arbitration_state(self, state: str, *, reason: str) -> None:
        previous = self._arbitration_state
        if previous == state:
            return
        self._arbitration_state = state
        logger.info(
            "Omni 回答仲裁状态变化: conversation=%s tenant=%s previous=%s current=%s reason=%s pending_default=%s",
            self.conversation_id,
            self.tenant_id,
            previous,
            state,
            reason,
            len(self._pending_default_sentences),
        )

    async def _complete_turn(
        self,
        *,
        reason: str = "ok",
        send_llm_end: bool = True,
    ) -> None:
        if self._finished.is_set():
            return
        answer = self._final_answer_text()
        if send_llm_end and self._llm_started:
            await self._send(
                {"type": "llm_end", "text": answer, "backend": "omni"}
            )
        if (
            reason not in {"dialog_silenced", "dialog_resumed"}
            and (self._last_user_text.strip() or answer)
        ):
            self._last_completed_turn = (self._last_user_text.strip(), answer)
        self._turn_active = False
        self._finished.set()
        await self._send_done(reason)
        logger.info(
            "Omni 语音轮次完成: conversation=%s reason=%s answer_chars=%s source=%s",
            self.conversation_id,
            reason,
            len(answer),
            self._response_mode,
        )

    async def _fail_turn(
        self,
        message: str,
        *,
        recoverable: bool = False,
        code: str = "",
        reason: str = "error",
    ) -> None:
        if self._finished.is_set():
            return
        payload = {
            "type": "error",
            "message": message,
            "recoverable": recoverable,
        }
        if code:
            payload["code"] = code
        await self._send(payload)
        self._turn_active = False
        self._finished.set()
        await self._send_done(reason)

    def _build_start_session_payload(self) -> dict[str, Any]:
        if REALTIME_DIALOG_DYNAMIC_NO_CACHE:
            self._dynamic_session_nonce = f"{int(time.time() * 1000)}-{self.conversation_id}"
        settings = self._voice_settings or OmniSessionSettings(
            tenant_id=self.tenant_id,
            speaker_id=REALTIME_DIALOG_SPEAKER,
            fallback_speaker_id=REALTIME_DIALOG_SPEAKER,
            model=REALTIME_DIALOG_MODEL,
            realtime_resource_id=REALTIME_DIALOG_RESOURCE_ID,
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="",
            speaking_style="",
            profile_version=0,
            clone_enabled=False,
        )
        persona = self._persona_settings
        system_role = persona.system_role if persona is not None else REALTIME_DIALOG_SYSTEM_ROLE
        if self.person_identity_verified and self.person_name:
            system_role = (
                f"{system_role}\n当前与你对话的人叫{self.person_name}。"
                "自然地称呼对方，但不要反复提及姓名，也不要声称记得未提供的信息。"
            )
        if self._person_memory_prompt:
            system_role = (
                f"{system_role}\n你已经认识当前用户。请自然利用下面的可靠人物记忆延续熟悉感，"
                "不要逐条复述，不要暴露内部标签或记忆检索过程；只有话题相关时才引用具体事实。\n"
                f"{self._person_memory_prompt}"
            )
        if REALTIME_DIALOG_DYNAMIC_NO_CACHE:
            system_role = (
                f"{system_role}\n动态问答当前临时关闭缓存：每一轮都重新组织回答。"
                "如果用户重复或近似重复提问，事实保持一致，但不要复用上一轮的原句、句式和顺序。"
                f"本轮会话标记：{self._dynamic_session_nonce}。"
            )
        speaking_style = persona.speaking_style if persona is not None else REALTIME_DIALOG_SPEAKING_STYLE
        if settings.clone_enabled and settings.speaking_style:
            speaking_style = f"{speaking_style}\n{settings.speaking_style}"[:4000]
        dialog: dict[str, Any] = {
            "bot_name": (
                persona.assistant_name
                if persona is not None
                else REALTIME_DIALOG_BOT_NAME
            ),
            "system_role": system_role,
            "speaking_style": speaking_style,
            "location": {"city": REALTIME_DIALOG_CITY},
            "extra": {
                "strict_audit": False,
                "audit_response": "这个问题我暂时不能回答，我们换个轻松的话题吧。",
                "input_mod": "keep_alive",
                "enable_loudness_norm": REALTIME_DIALOG_ENABLE_LOUDNESS_NORM,
                "enable_conversation_truncate": True,
                "model": settings.model,
            },
        }
        context = [] if REALTIME_DIALOG_DYNAMIC_NO_CACHE else self._build_dialog_context()
        if context:
            dialog["dialog_context"] = context
        tts: dict[str, Any] = {
            "speaker": settings.speaker_id,
            "audio_config": {
                "channel": 1,
                "format": REALTIME_DIALOG_OUTPUT_FORMAT,
                "sample_rate": REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
                "speech_rate": max(-50, min(100, REALTIME_DIALOG_SPEECH_RATE)),
                "loudness_rate": max(-50, min(100, REALTIME_DIALOG_LOUDNESS_RATE)),
            },
        }
        if settings.clone_enabled:
            tts["extra"] = {"tts_2.0_model": settings.tts_2_0_model}
        return {
            "asr": {
                "extra": {
                    "enable_custom_vad": REALTIME_DIALOG_ENABLE_CUSTOM_VAD,
                    "end_smooth_window_ms": self._end_smooth_window_ms(),
                }
            },
            "tts": tts,
            "dialog": dialog,
        }

    def _build_dialog_context(self) -> list[dict[str, str]]:
        pairs: list[dict[str, str]] = []
        pending_user = ""
        for item in self._context:
            if item.get("role") == "user":
                pending_user = str(item.get("content") or "").strip()
                continue
            if item.get("role") == "assistant" and pending_user:
                answer = str(item.get("content") or "").strip()
                if answer:
                    pairs.extend(
                        [
                            {"role": "user", "text": pending_user},
                            {"role": "assistant", "text": answer},
                        ]
                    )
                pending_user = ""
        return pairs[-6:]

    def _append_local_context(self, user_text: str, answer: str) -> None:
        if user_text and answer:
            turn = [
                {"role": "user", "content": user_text[:500]},
                {"role": "assistant", "content": answer[:500]},
            ]
            self._context.extend(turn)
            self._context = self._context[-6:]
            self._person_memory_context.extend(turn)
            self._person_memory_context = self._person_memory_context[-20:]

    def _record_interrupted_context(
        self,
        *,
        previous_user_text: str,
        assistant_text: str,
        active_sentence: str,
        played_ms: int,
        client_mode: str,
    ) -> None:
        """Keep barge-in context for the next model turn without committing memory."""

        user_text = (previous_user_text or self._last_user_text or "").strip()[:500]
        answer_text = (
            assistant_text or self._final_answer_text() or active_sentence or ""
        ).strip()
        active_text = (active_sentence or "").strip()
        if not user_text or not answer_text:
            logger.info(
                "Omni 抢话上下文为空，跳过短期记忆: conversation=%s tenant=%s user_chars=%s answer_chars=%s mode=%s",
                self.conversation_id,
                self.tenant_id,
                len(user_text),
                len(answer_text),
                client_mode or "(unknown)",
            )
            return

        played_ms = max(0, int(played_ms or 0))
        note_parts = ["上一轮回答被用户打断"]
        if played_ms > 0:
            note_parts.append(f"浏览器已播放约 {played_ms}ms")
        if active_text and active_text not in answer_text:
            note_parts.append(f"打断时正在播放: {active_text[:160]}")
        note_parts.append("下一轮要把用户新说的话当作补充、纠正或追问来理解")
        assistant_note = f"{answer_text[:360]}（{'；'.join(note_parts)}。）"
        interrupted_pair = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_note[:500]},
        ]
        self._context.extend(interrupted_pair)
        self._context = self._context[-6:]
        logger.info(
            "Omni 已保留抢话短期上下文: conversation=%s tenant=%s user_chars=%s answer_chars=%s active_chars=%s played_ms=%s mode=%s",
            self.conversation_id,
            self.tenant_id,
            len(user_text),
            len(answer_text),
            len(active_text),
            played_ms,
            client_mode or "(unknown)",
        )

    def _reset_turn_state(self) -> None:
        self._tts_expectation.reset()
        self._finished.clear()
        self._asr_ended.clear()
        self._input_ended = False
        self._last_user_text = ""
        self._response_mode = "routing"
        self._arbitration_state = ARBITRATION_ROUTING
        self._default_fallback_released = False
        self._current_tts_type = ""
        self._current_tts_text = ""
        self._current_reply_id = ""
        self._current_audio_chunks = []
        self._pending_response_text = ""
        self._reply_texts = {}
        self._allowed_reply_ids = set()
        self._allowed_reply_order = []
        self._emitted_reply_texts = {}
        self._response_types_seen = set()
        self._pending_default_sentences = []
        self._default_response_ended = False
        self._default_tts_ended.clear()
        self._answer_parts = []
        self._sentence_index = 0
        self._llm_started = False
        self._late_audio_chunks = 0
        self._late_audio_bytes = 0
        self._late_asr_events = 0
        self._terminal_sent = False

    def _build_external_rag(
        self,
        query: str,
        precomputed_results: list[Any] | None = None,
    ) -> str:
        started_at = time.perf_counter()
        retrieval_source = (
            "intent_probe" if precomputed_results is not None else "direct"
        )
        results = list(precomputed_results or [])
        if precomputed_results is None:
            results = get_knowledge_service(self.tenant_id).search(
                query,
                top_k=REALTIME_DIALOG_RAG_TOP_K,
                min_score=REALTIME_DIALOG_RAG_MIN_SCORE,
            )
        if not results:
            logger.info(
                "Omni RAG 无命中: conversation=%s query=%s retrieval=%s search_ms=%.0f",
                self.conversation_id,
                query,
                retrieval_source,
                (time.perf_counter() - started_at) * 1000,
            )
            return ""

        max_chars = max(256, min(4000, REALTIME_DIALOG_RAG_MAX_CHARS))
        items: list[dict[str, str]] = []
        for result in results:
            title = str(result.title or result.source_path or "企业知识").strip()
            content = str(result.content or "").strip()
            if not content:
                continue
            remaining = max_chars - len(json.dumps(items, ensure_ascii=False)) - len(title) - 48
            if remaining <= 0:
                break
            candidate = {"title": title, "content": content[:remaining]}
            trial = json.dumps([*items, candidate], ensure_ascii=False)
            if len(trial) > max_chars:
                overflow = len(trial) - max_chars
                candidate["content"] = candidate["content"][: max(0, len(candidate["content"]) - overflow)]
                trial = json.dumps([*items, candidate], ensure_ascii=False)
            if candidate["content"]:
                items.append(candidate)
            if len(trial) >= max_chars:
                break
        payload = json.dumps(items, ensure_ascii=False)
        logger.info(
            "Omni RAG 命中: conversation=%s query=%s hits=%s payload_chars=%s retrieval=%s build_ms=%.0f sources=%s",
            self.conversation_id,
            query,
            len(items),
            len(payload),
            retrieval_source,
            (time.perf_counter() - started_at) * 1000,
            [item["title"] for item in items],
        )
        return payload if items else ""

    def _build_person_context_external_rag(
        self,
        query: str,
        person_reply,
        required_facts: list[str],
        *,
        constraints: list[str],
    ) -> str:
        goal = (
            person_reply.response_goal
            or "按服务端可信人物上下文，自然回答用户最新问题。"
        )
        lines = [
            "这是服务端可信人物上下文材料，只用于回答用户最新问题。",
            f"业务场景：{person_reply.intent}",
            f"用户最新问题：{query}",
            f"回答目标：{goal}",
            "必须遵守的可信事实：",
        ]
        for fact in required_facts:
            fact = str(fact or "").strip()
            if fact:
                lines.append(f"- {fact}")
        if constraints:
            lines.append("表达约束：")
            for item in constraints:
                item = str(item or "").strip()
                if item:
                    lines.append(f"- {item}")
        lines.extend(
            [
                "输出要求：直接对用户说话，不要说“根据材料”“系统显示”“可信事实”。",
                "输出要求：不要逐字复述本材料，不要输出项目符号或标题。",
            ]
        )
        content = "\n".join(lines)
        max_chars = max(512, min(4000, REALTIME_DIALOG_RAG_MAX_CHARS))
        payload = json.dumps(
            [
                {
                    "title": "人物上下文",
                    "content": content[:max_chars],
                }
            ],
            ensure_ascii=False,
        )
        logger.info(
            "Omni 人物上下文外部 RAG 已构建: conversation=%s intent=%s facts=%s payload_chars=%s",
            self.conversation_id,
            person_reply.intent,
            len(required_facts),
            len(payload),
        )
        return payload

    async def _send_dialog_silence_state(
        self,
        result: DialogSilenceResult,
        *,
        active: bool,
    ) -> None:
        dynamic_feedback = (
            result.action in {ACTION_MUTE, ACTION_WAKE}
            and not (result.route_text or "").strip()
        )
        await self._send(
            {
                "type": "dialog_silence",
                "active": active,
                "assistantName": result.assistant_name,
                "matchedAlias": result.matched_alias,
                "statusText": result.status_text,
                "responseText": "" if dynamic_feedback else result.response_text,
                "dynamicFeedback": dynamic_feedback,
                "backend": "omni",
            }
        )

    async def _speak_scene_response(
        self,
        canonical_text: str,
        *,
        command: str,
        scene: str,
        user_text: str = "",
        required_facts: list[str] | None = None,
        response_goal: str = "",
        user_info: dict | None = None,
        constraints: list[str] | None = None,
    ) -> str:
        if scene not in {"dialog_silence_mute", "dialog_silence_wake"}:
            return await super()._speak_scene_response(
                canonical_text,
                command=command,
                scene=scene,
                user_text=user_text,
                required_facts=required_facts,
                response_goal=response_goal,
                user_info=user_info,
                constraints=constraints,
            )

        spoken = await self._generate_scene_reply(
            canonical_text,
            scene=scene,
            user_text=user_text,
            required_facts=required_facts,
            response_goal=response_goal,
            user_info=user_info
            or {
                "person_name": self.person_name,
                "identity_verified": str(self.person_identity_verified),
                "device_id": self.device_id,
            },
            constraints=constraints,
        )
        logger.info(
            "Omni 静音控制动态反馈已生成: conversation=%s tenant=%s scene=%s answer_chars=%s spoken=%s",
            self.conversation_id,
            self.tenant_id,
            scene,
            len(spoken),
            spoken[:120],
        )
        await self._speak_command_response(spoken, command=command)
        return spoken

    async def _send_person_context_external_response(
        self,
        person_reply,
        external_rag: str,
    ) -> None:
        reason_prefix = person_reply.intent
        try:
            default_wait_seconds = (
                await self._wait_for_default_tts_end_for_external_rag(
                    payload_chars=len(external_rag),
                )
            )
            self._response_mode = TTS_TYPE_EXTERNAL_RAG
            self._set_arbitration_state(
                ARBITRATION_EXTERNAL_PENDING,
                reason=f"{reason_prefix}_selected",
            )
            logger.info(
                "Omni 发送人物上下文外部 RAG 事件: conversation=%s tenant=%s intent=%s payload_chars=%s pending_default=%s default_wait_ms=%.0f",
                self.conversation_id,
                self.tenant_id,
                person_reply.intent,
                len(external_rag),
                len(self._pending_default_sentences),
                default_wait_seconds * 1000,
            )
            await self._request_external_rag_response(
                lambda: self._require_transport().send_external_rag(external_rag),
            )
            if self._arbitration_state != ARBITRATION_EXTERNAL_COMMITTED:
                reason = f"{reason_prefix}_no_external_audio"
                logger.warning(
                    "Omni 人物上下文外部 RAG 完成但未提交音频: conversation=%s tenant=%s intent=%s state=%s pending_default=%s",
                    self.conversation_id,
                    self.tenant_id,
                    person_reply.intent,
                    self._arbitration_state,
                    len(self._pending_default_sentences),
                )
                await self._expire_external_generation(reason)
                await self._fallback_person_context_external_response(
                    person_reply,
                    reason=reason,
                )
                return
            await self._complete_turn()
        except Exception as exc:
            reason = f"{reason_prefix}_external_error"
            logger.exception(
                "Omni 人物上下文外部 RAG 失败: conversation=%s tenant=%s intent=%s state=%s pending_default=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                person_reply.intent,
                self._arbitration_state,
                len(self._pending_default_sentences),
                type(exc).__name__,
                exc,
            )
            if self._arbitration_state == ARBITRATION_EXTERNAL_COMMITTED:
                if not self._finished.is_set():
                    await self._complete_turn(reason=reason)
                return
            if self._arbitration_state == ARBITRATION_EXTERNAL_PENDING:
                await self._expire_external_generation(reason)
            await self._fallback_person_context_external_response(
                person_reply,
                reason=reason,
            )

    async def _fallback_person_context_external_response(
        self,
        person_reply,
        *,
        reason: str,
    ) -> None:
        if self._finished.is_set():
            return
        released = await self._release_default_response(reason=reason)
        if released or self._finished.is_set():
            return
        spoken = self._person_context_scene_unavailable_text(person_reply)
        await self._send({"type": "llm_delta", "text": spoken})
        await self._synthesize_sentence(spoken, 1)
        await self._complete_turn(reason=reason)

    def _tts_type_allowed(self, tts_type: str) -> bool:
        if self._response_mode == "audit":
            return tts_type == TTS_TYPE_AUDIT
        if self._response_mode == "default":
            return tts_type in {TTS_TYPE_DEFAULT, TTS_TYPE_AUDIT}
        if self._response_mode == TTS_TYPE_EXTERNAL_RAG:
            return tts_type in {TTS_TYPE_EXTERNAL_RAG, TTS_TYPE_AUDIT}
        if self._response_mode == TTS_TYPE_CHAT_TEXT:
            return tts_type in {TTS_TYPE_CHAT_TEXT, TTS_TYPE_AUDIT}
        return False

    def _require_transport(self) -> VolcRealtimeDialogClient:
        if self.transport is None:
            raise VoicePipelineError("Omni transport is unavailable")
        return self.transport

    @staticmethod
    def _extract_asr_result(payload: Any) -> tuple[str, bool]:
        if not isinstance(payload, dict):
            return "", True
        results = payload.get("results")
        if not isinstance(results, list):
            return "", True
        text = ""
        is_interim = True
        for result in results:
            if not isinstance(result, dict):
                continue
            value = str(result.get("text") or "").strip()
            if value:
                text = value
                is_interim = bool(result.get("is_interim", True))
        return text, is_interim

    @staticmethod
    def _extract_string(payload: Any, key: str) -> str:
        if not isinstance(payload, dict):
            return ""
        value = payload.get(key)
        return str(value).strip() if value is not None else ""

    @classmethod
    def _extract_nested_string(cls, payload: Any, key: str) -> str:
        if isinstance(payload, dict):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            for item in payload.values():
                found = cls._extract_nested_string(item, key)
                if found:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = cls._extract_nested_string(item, key)
                if found:
                    return found
        return ""

    @classmethod
    def _extract_assistant_text(cls, payload: Any) -> str:
        preferred_keys = (
            "answer",
            "assistant_text",
            "bot_text",
            "response",
            "response_text",
            "output_text",
            "tts_text",
            "speech_text",
            "text",
            "content",
        )
        if isinstance(payload, dict):
            for key in preferred_keys:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for item in payload.values():
                found = cls._extract_assistant_text(item)
                if found:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = cls._extract_assistant_text(item)
                if found:
                    return found
        return ""

    @classmethod
    def _payload_keys(cls, payload: Any) -> list[str]:
        keys: list[str] = []
        if isinstance(payload, dict):
            keys.extend(str(key) for key in payload.keys())
            for item in payload.values():
                keys.extend(cls._payload_keys(item))
        elif isinstance(payload, list):
            for item in payload:
                keys.extend(cls._payload_keys(item))
        return keys[:20]

    @staticmethod
    def _merge_stream_text(current: str, incoming: str) -> str:
        current = (current or "").strip()
        incoming = (incoming or "").strip()
        if not current:
            return incoming
        if not incoming or incoming == current:
            return current
        if incoming.startswith(current):
            return incoming
        if current.endswith(incoming):
            return current
        return current + incoming

    def _allow_reply(self, reply_id: str) -> None:
        reply_id = (reply_id or "").strip()
        if not reply_id or reply_id in self._allowed_reply_ids:
            return
        self._allowed_reply_ids.add(reply_id)
        self._allowed_reply_order.append(reply_id)

    def _final_answer_text(self) -> str:
        reply_answer = "".join(
            self._reply_texts.get(reply_id, "")
            for reply_id in self._allowed_reply_order
        )
        return (reply_answer or "".join(self._answer_parts)).strip()

    async def _emit_reply_text(self, reply_id: str, text: str) -> None:
        reply_id = (reply_id or "").strip()
        text = (text or "").strip()
        if not reply_id or not text or reply_id not in self._allowed_reply_ids:
            return
        current = self._reply_texts.get(reply_id, "")
        current = self._merge_stream_text(current, text)
        self._reply_texts[reply_id] = current
        emitted = self._emitted_reply_texts.get(reply_id, "")
        if current == emitted:
            return
        delta = current[len(emitted) :] if emitted and current.startswith(emitted) else current
        self._emitted_reply_texts[reply_id] = current
        if delta:
            await self._send({"type": "llm_delta", "text": delta})

    @staticmethod
    def _is_idle_timeout(exc: Exception) -> bool:
        message = str(exc)
        return "DialogAudioIdleTimeoutError" in message or "52000042" in message

    @staticmethod
    def _end_smooth_window_ms() -> int:
        return max(500, min(50000, REALTIME_DIALOG_END_SMOOTH_WINDOW_MS))

    @staticmethod
    def _validate_settings(settings: OmniSessionSettings) -> None:
        if settings.model != OMNI_MODEL:
            raise VoicePipelineError(
                f"Omni backend requires REALTIME_DIALOG_MODEL={OMNI_MODEL}, "
                f"got {settings.model}"
            )
        if settings.realtime_resource_id != "volc.speech.dialog":
            raise VoicePipelineError(
                "Omni backend requires realtime resource volc.speech.dialog"
            )
        if settings.clone_enabled and settings.tts_2_0_model != "expressive":
            raise VoicePipelineError(
                "O2.0 cloned voice requires tts_2.0_model=expressive"
            )
        if REALTIME_DIALOG_OUTPUT_FORMAT != "pcm_s16le":
            raise VoicePipelineError(
                "Omni browser backend currently requires REALTIME_DIALOG_OUTPUT_FORMAT=pcm_s16le"
            )
        if REALTIME_DIALOG_OUTPUT_SAMPLE_RATE != 24000:
            raise VoicePipelineError(
                "Omni browser backend currently requires REALTIME_DIALOG_OUTPUT_SAMPLE_RATE=24000"
            )
