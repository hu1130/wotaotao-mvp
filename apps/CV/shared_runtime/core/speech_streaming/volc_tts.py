"""Volcengine streaming TTS provider."""

from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator

import websockets

from config import (
    VOLC_TTS_ACCESS_KEY,
    VOLC_TTS_APP_KEY,
    VOLC_TTS_ENCODING,
    VOLC_TTS_RESOURCE_ID,
    VOLC_TTS_SAMPLE_RATE,
    VOLC_TTS_URL,
    VOLC_TTS_VOICE,
)
from core.speech_streaming import volc_protocol as protocol


class VolcTtsError(RuntimeError):
    pass


class VolcStreamingTtsClient:
    def __init__(self):
        self.url = VOLC_TTS_URL
        self.app_key = VOLC_TTS_APP_KEY
        self.access_key = VOLC_TTS_ACCESS_KEY
        self.resource_id = VOLC_TTS_RESOURCE_ID
        self.voice = VOLC_TTS_VOICE
        self.encoding = VOLC_TTS_ENCODING
        self.sample_rate = VOLC_TTS_SAMPLE_RATE

    @property
    def ready(self) -> bool:
        return bool(self.url and self.app_key and self.access_key and self.resource_id and self.voice)

    @property
    def mime_type(self) -> str:
        if self.encoding.lower() == "mp3":
            return "audio/mpeg"
        if self.encoding.lower() in {"ogg_opus", "opus"}:
            return "audio/ogg"
        return "audio/wav"

    async def synthesize(
        self,
        text: str,
        *,
        speaker_id: str | None = None,
        tts_2_0_model: str = "",
    ) -> AsyncGenerator[bytes, None]:
        text = (text or "").strip()
        if not text:
            return
        if not self.ready:
            raise VolcTtsError("Volcengine TTS is not configured")
        speaker = (speaker_id or self.voice or "").strip()
        if not speaker:
            raise VolcTtsError("Volcengine TTS speaker is not configured")

        headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        try:
            websocket = await _websocket_connect(self.url, headers=headers)
        except Exception as exc:
            raise VolcTtsError(
                "Volcengine TTS WebSocket 握手失败。"
                "如果是 HTTP 403，通常是 VOLC_TTS_APP_KEY / VOLC_TTS_ACCESS_KEY "
                "没有开通语音合成资源，或 VOLC_TTS_RESOURCE_ID / VOLC_TTS_VOICE "
                "不属于当前账号。"
                f"原始错误: {exc}"
            ) from exc
        try:
            await websocket.send(
                protocol.build_full_client_request(
                    self._payload(text, speaker, tts_2_0_model=tts_2_0_model)
                )
            )
            async for raw in websocket:
                if not isinstance(raw, bytes):
                    continue
                msg = protocol.parse_message(raw)
                if msg.type == protocol.MsgType.AUDIO_ONLY_SERVER:
                    if msg.payload:
                        yield msg.payload
                elif msg.type == protocol.MsgType.FULL_SERVER_RESPONSE:
                    if msg.event == protocol.EventType.SESSION_FINISHED:
                        break
                elif msg.type == protocol.MsgType.ERROR:
                    payload = msg.payload.decode("utf-8", "ignore")
                    raise VolcTtsError(
                        f"Volcengine TTS error {msg.error_code}: {payload}. "
                        f"当前 VOLC_TTS_RESOURCE_ID={self.resource_id}, "
                        f"speaker={_mask_speaker_id(speaker)}。"
                        "请确认音色属于这个语音合成资源；"
                        "Doubao-语音合成-2.0 通常需要 seed-tts-2.0 + 2.0 音色，"
                        "realtime dialogue 的 *_bigtts 音色不一定能直接复用于 standalone TTS。"
                    )
        finally:
            await websocket.close()

    def _payload(
        self,
        text: str,
        speaker: str | None = None,
        *,
        tts_2_0_model: str = "",
    ) -> bytes:
        additions = {"disable_markdown_filter": False}
        if tts_2_0_model:
            additions["tts_2.0_model"] = tts_2_0_model
        request = {
            "user": {"uid": str(uuid.uuid4())},
            "req_params": {
                "speaker": speaker or self.voice,
                "audio_params": {
                    "format": self.encoding,
                    "sample_rate": self.sample_rate,
                    "enable_timestamp": True,
                },
                "text": text,
                "additions": json.dumps(additions, ensure_ascii=False),
            },
        }
        return json.dumps(request, ensure_ascii=False).encode("utf-8")


async def _websocket_connect(url: str, headers: dict[str, str]):
    try:
        return await websockets.connect(
            url,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
            ping_interval=None,
        )
    except TypeError:
        return await websockets.connect(
            url,
            extra_headers=headers,
            max_size=10 * 1024 * 1024,
            ping_interval=None,
        )


def _mask_speaker_id(speaker_id: str) -> str:
    value = (speaker_id or "").strip()
    if len(value) <= 7:
        return value[:3] + "…"
    return value[:6] + "…"
