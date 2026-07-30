"""Unified fixed-speech TTS provider selection.

Fixed avatar phrases must use the same tenant voice profile as the realtime
Omni path on the server. Edge remains available only as an explicit
compatibility provider for client-side legacy environments.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from dataclasses import dataclass
from typing import Any, AsyncIterator

from config import (
    FIXED_TTS_ALLOW_EDGE_FALLBACK,
    FIXED_TTS_PROVIDER,
    FIXED_TTS_TIMEOUT_SECONDS,
    FIXED_TTS_TENANT_ID,
    REALTIME_DIALOG_ACCESS_KEY,
    REALTIME_DIALOG_APP_KEY,
    REALTIME_DIALOG_APP_ID,
    REALTIME_DIALOG_BASE_URL,
    REALTIME_DIALOG_BOT_NAME,
    REALTIME_DIALOG_CITY,
    REALTIME_DIALOG_ENABLE_LOUDNESS_NORM,
    REALTIME_DIALOG_LOUDNESS_RATE,
    REALTIME_DIALOG_MODEL,
    REALTIME_DIALOG_OUTPUT_FORMAT,
    REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
    REALTIME_DIALOG_RESOURCE_ID,
    REALTIME_DIALOG_SPEAKING_STYLE,
    REALTIME_DIALOG_SPEECH_RATE,
    REALTIME_DIALOG_SYSTEM_ROLE,
    TTS_VOICE,
    TTS_VOICE_BY_MODEL,
    VOLC_TTS_VOICE,
)
from core.speech_streaming.volc_realtime import (
    VolcRealtimeDialogClient,
    VolcRealtimeDialogConfig,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FixedTtsVoice:
    provider: str
    tenant_id: str
    speaker_id: str
    model: str = "1.2.1.1"
    realtime_resource_id: str = "volc.speech.dialog"
    speaking_style: str = ""
    profile_version: int = 0
    clone_enabled: bool = False
    tts_2_0_model: str = ""

    @property
    def masked_speaker(self) -> str:
        return mask_speaker_id(self.speaker_id)


class FixedTtsClient:
    """Generates fixed phrases with the configured project-wide voice policy."""

    def __init__(
        self,
        *,
        tenant_id: str | None = None,
        provider: str | None = None,
        allow_edge_fallback: bool | None = None,
    ) -> None:
        self.tenant_id = (tenant_id or FIXED_TTS_TENANT_ID or "default").strip()
        self.provider = _normalize_provider(provider or FIXED_TTS_PROVIDER)
        self.allow_edge_fallback = (
            FIXED_TTS_ALLOW_EDGE_FALLBACK
            if allow_edge_fallback is None
            else bool(allow_edge_fallback)
        )

    def build_cache_material(self, request: Any) -> str:
        voice = self.resolve_request(request)
        return "|".join(
            [
                "fixed-tts",
                voice.provider,
                voice.tenant_id,
                voice.speaker_id,
                str(voice.profile_version),
                "clone" if voice.clone_enabled else "fallback",
                voice.tts_2_0_model,
                str(getattr(request, "text", "") or ""),
            ]
        )

    def cache_extension(self, request: Any | None = None) -> str:
        voice = self.resolve_request(request)
        if voice.provider == "edge":
            return ".mp3"
        return ".wav"

    async def synthesize_to_file_async(self, request: Any, path: str) -> None:
        text = str(getattr(request, "text", "") or "").strip()
        if not text:
            raise ValueError("fixed TTS text is empty")
        voice = self.resolve_request(request)
        logger.info(
            "固定语音生成: provider=%s tenant=%s speaker=%s clone=%s version=%s event=%s",
            voice.provider,
            voice.tenant_id,
            voice.masked_speaker,
            voice.clone_enabled,
            voice.profile_version,
            getattr(request, "event_type", "") or "raw",
        )
        if voice.provider == "edge":
            await self._synthesize_edge_to_file(text, path, voice.speaker_id)
            return
        audio, metadata = await self._synthesize_o2_audio(text, voice)
        with open(path, "wb") as audio_file:
            audio_file.write(audio)
        logger.info(
            "固定语音 O2 合成完成: tenant=%s speaker=%s bytes=%s duration_ms=%s",
            voice.tenant_id,
            voice.masked_speaker,
            metadata["bytes"],
            metadata["duration_ms"],
        )

    async def stream_audio_chunks_async(self, request: Any) -> AsyncIterator[bytes]:
        text = str(getattr(request, "text", "") or "").strip()
        if not text:
            raise ValueError("fixed TTS text is empty")
        voice = self.resolve_request(request)
        if voice.provider == "edge":
            raise RuntimeError("fixed TTS streaming requires Volcengine O2 provider")
        logger.info(
            "固定语音流式生成: provider=%s tenant=%s speaker=%s clone=%s version=%s event=%s",
            voice.provider,
            voice.tenant_id,
            voice.masked_speaker,
            voice.clone_enabled,
            voice.profile_version,
            getattr(request, "event_type", "") or "raw",
        )
        async for chunk in self._stream_o2_audio_chunks(text, voice):
            yield chunk

    def resolve_request(self, request: Any | None = None) -> FixedTtsVoice:
        tenant_id = (
            str(getattr(request, "tenant_id", "") or "").strip()
            if request is not None
            else ""
        ) or self.tenant_id
        requested_voice = (
            str(getattr(request, "voice", "") or "").strip()
            if request is not None
            else ""
        )
        if self.provider == "edge":
            return self._edge_voice(tenant_id, requested_voice)

        explicit_volc_voice = self._explicit_volc_voice(tenant_id, requested_voice)
        if explicit_volc_voice is not None:
            if REALTIME_DIALOG_APP_ID.strip() and REALTIME_DIALOG_ACCESS_KEY.strip():
                logger.info(
                    "固定语音使用显式火山音色: tenant=%s speaker=%s",
                    tenant_id,
                    explicit_volc_voice.masked_speaker,
                )
                return explicit_volc_voice
            if self.allow_edge_fallback:
                logger.warning(
                    "固定语音显式火山音色缺少 O2.0 凭证，显式回退 Edge: tenant=%s speaker=%s",
                    tenant_id,
                    explicit_volc_voice.masked_speaker,
                )
                return self._edge_voice(tenant_id, requested_voice)
            raise RuntimeError("Volcengine O2 fixed TTS is not configured")

        try:
            voice = self._resolve_tenant_voice(tenant_id)
        except Exception as exc:
            if not self.allow_edge_fallback:
                logger.warning(
                    "固定语音租户音色解析失败: tenant=%s provider=%s error=%s",
                    tenant_id,
                    self.provider,
                    exc,
                )
                raise
            logger.warning(
                "固定语音租户音色解析失败，显式回退 Edge: tenant=%s error=%s",
                tenant_id,
                exc,
            )
            return self._edge_voice(tenant_id, requested_voice)

        if REALTIME_DIALOG_APP_ID.strip() and REALTIME_DIALOG_ACCESS_KEY.strip():
            return voice
        if self.allow_edge_fallback:
            logger.warning(
                "固定语音 O2.0 凭证未配置，显式回退 Edge: tenant=%s speaker=%s",
                tenant_id,
                voice.masked_speaker,
            )
            return self._edge_voice(tenant_id, requested_voice)
        raise RuntimeError("Volcengine O2 fixed TTS is not configured")

    @staticmethod
    def _explicit_volc_voice(
        tenant_id: str,
        requested_voice: str,
    ) -> FixedTtsVoice | None:
        voice = (requested_voice or "").strip()
        if not voice.startswith("zh_"):
            return None
        return FixedTtsVoice(
            provider="volc",
            tenant_id=tenant_id,
            speaker_id=voice,
            model=REALTIME_DIALOG_MODEL,
            realtime_resource_id=REALTIME_DIALOG_RESOURCE_ID,
            speaking_style=REALTIME_DIALOG_SPEAKING_STYLE,
            profile_version=0,
            clone_enabled=False,
            tts_2_0_model="",
        )

    def _resolve_tenant_voice(self, tenant_id: str) -> FixedTtsVoice:
        try:
            from core.tenant_voice.service import get_tenant_voice_profile_service
        except Exception:
            return FixedTtsVoice(
                provider="volc",
                tenant_id=tenant_id,
                speaker_id=VOLC_TTS_VOICE,
                speaking_style=REALTIME_DIALOG_SPEAKING_STYLE,
            )
        settings = get_tenant_voice_profile_service().resolve(tenant_id)
        return FixedTtsVoice(
            provider="volc",
            tenant_id=settings.tenant_id,
            speaker_id=settings.speaker_id,
            model=settings.model,
            realtime_resource_id=settings.realtime_resource_id,
            speaking_style=settings.speaking_style,
            profile_version=settings.profile_version,
            clone_enabled=settings.clone_enabled,
            tts_2_0_model=settings.tts_2_0_model if settings.clone_enabled else "",
        )

    async def _synthesize_o2_audio(
        self,
        text: str,
        voice: FixedTtsVoice,
    ) -> tuple[bytes, dict[str, int]]:
        chunks = [
            chunk
            async for chunk in self._stream_o2_audio_chunks(text, voice)
        ]
        return _assemble_wav_audio(
            chunks,
            sample_rate=REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
        )

    async def _stream_o2_audio_chunks(
        self,
        text: str,
        voice: FixedTtsVoice,
    ) -> AsyncIterator[bytes]:
        self._validate_o2_output()
        config = VolcRealtimeDialogConfig(
            app_id=REALTIME_DIALOG_APP_ID,
            app_key=REALTIME_DIALOG_APP_KEY,
            access_key=REALTIME_DIALOG_ACCESS_KEY,
            base_url=REALTIME_DIALOG_BASE_URL,
            resource_id=voice.realtime_resource_id,
            connect_timeout_seconds=max(5.0, FIXED_TTS_TIMEOUT_SECONDS),
            ping_interval_seconds=20.0,
            ping_timeout_seconds=10.0,
            close_timeout_seconds=5.0,
        )
        client = VolcRealtimeDialogClient(
            config,
            start_session_payload=self._build_o2_start_session_payload(voice),
        )
        started = False
        ended = False
        chunk_count = 0
        try:
            await client.connect()
            await client.send_text_query(self._exact_repeat_query(text))
            deadline = max(5.0, FIXED_TTS_TIMEOUT_SECONDS)
            while not ended:
                response = await asyncio.wait_for(client.receive(), timeout=deadline)
                event = int(response.get("event") or 0)
                payload = response.get("payload_msg")
                if event == 350:
                    started = True
                elif event == 352 and isinstance(payload, bytes):
                    chunk_count += 1
                    yield payload
                elif response.get("message_type") == "SERVER_ACK" and isinstance(
                    payload,
                    bytes,
                ):
                    chunk_count += 1
                    yield payload
                elif event == 359:
                    ended = True
                elif event == 599:
                    raise RuntimeError(f"O2 fixed TTS error: {payload}")
        finally:
            await client.close()
        if not started or not ended or chunk_count <= 0:
            raise RuntimeError("O2 fixed TTS did not complete 350 -> 352 -> 359")

    def _build_o2_start_session_payload(self, voice: FixedTtsVoice) -> dict[str, Any]:
        speaking_style = REALTIME_DIALOG_SPEAKING_STYLE
        if voice.clone_enabled and voice.speaking_style:
            speaking_style = f"{speaking_style}\n{voice.speaking_style}"[:4000]
        tts: dict[str, Any] = {
            "speaker": voice.speaker_id,
            "audio_config": {
                "channel": 1,
                "format": REALTIME_DIALOG_OUTPUT_FORMAT,
                "sample_rate": REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
                "speech_rate": max(-50, min(100, REALTIME_DIALOG_SPEECH_RATE)),
                "loudness_rate": max(-50, min(100, REALTIME_DIALOG_LOUDNESS_RATE)),
            },
        }
        if voice.clone_enabled:
            tts["extra"] = {"tts_2.0_model": voice.tts_2_0_model}
        return {
            "asr": {"extra": {"enable_custom_vad": True, "end_smooth_window_ms": 1500}},
            "tts": tts,
            "dialog": {
                "bot_name": REALTIME_DIALOG_BOT_NAME,
                "system_role": (
                    f"{REALTIME_DIALOG_SYSTEM_ROLE}\n"
                    "固定语音合成任务中，你必须只复述用户要求复述的引号内容，"
                    "不得添加解释、称呼、标点或其它文字。"
                ),
                "speaking_style": speaking_style,
                "location": {"city": REALTIME_DIALOG_CITY},
                "extra": {
                    "strict_audit": False,
                    "input_mod": "keep_alive",
                    "enable_loudness_norm": REALTIME_DIALOG_ENABLE_LOUDNESS_NORM,
                    "model": voice.model,
                },
            },
        }

    @staticmethod
    def _exact_repeat_query(text: str) -> str:
        safe_text = text.strip().replace("“", "「").replace("”", "」")
        return f"请只复述引号内的内容，不要增加、删减或改写任何字：『{safe_text}』"

    @staticmethod
    def _validate_o2_output() -> None:
        if REALTIME_DIALOG_OUTPUT_FORMAT != "pcm_s16le":
            raise RuntimeError(
                "fixed O2 TTS requires REALTIME_DIALOG_OUTPUT_FORMAT=pcm_s16le"
            )
        if REALTIME_DIALOG_OUTPUT_SAMPLE_RATE != 24000:
            raise RuntimeError(
                "fixed O2 TTS requires REALTIME_DIALOG_OUTPUT_SAMPLE_RATE=24000"
            )

    @staticmethod
    async def _synthesize_edge_to_file(text: str, path: str, voice: str) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice)
        with open(path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])

    @staticmethod
    def _edge_voice(tenant_id: str, voice_or_model: str) -> FixedTtsVoice:
        voice = TTS_VOICE_BY_MODEL.get(voice_or_model, voice_or_model) or TTS_VOICE
        return FixedTtsVoice(
            provider="edge",
            tenant_id=tenant_id,
            speaker_id=voice,
        )


def mask_speaker_id(speaker_id: str) -> str:
    value = (speaker_id or "").strip()
    if len(value) <= 7:
        return value[:3] + "…"
    return value[:6] + "…"


def _normalize_provider(provider: str) -> str:
    value = (provider or "volc").strip().lower()
    if value in {"volc", "volcengine", "clone", "cloned"}:
        return "volc"
    if value == "edge":
        return "edge"
    raise ValueError(f"Unsupported FIXED_TTS_PROVIDER={provider!r}")


def _assemble_wav_audio(
    chunks: list[bytes],
    *,
    sample_rate: int,
) -> tuple[bytes, dict[str, int]]:
    pcm = b"".join(chunks)
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    audio = output.getvalue()
    duration_ms = int(len(pcm) / (sample_rate * 2) * 1000) if sample_rate > 0 else 0
    return audio, {"bytes": len(audio), "duration_ms": duration_ms}
