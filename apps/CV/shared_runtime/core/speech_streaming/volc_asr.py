"""Volcengine streaming ASR provider."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import websockets

from config import (
    VOLC_ASR_ACCESS_KEY,
    VOLC_ASR_APP_KEY,
    VOLC_ASR_AUDIO_CODEC,
    VOLC_ASR_AUDIO_FORMAT,
    VOLC_ASR_RESOURCE_ID,
    VOLC_ASR_SAMPLE_RATE,
    VOLC_ASR_URL,
)
from core.speech_streaming import volc_protocol as protocol

logger = logging.getLogger(__name__)


class VolcAsrError(RuntimeError):
    pass


class VolcStreamingAsrClient:
    def __init__(self):
        self.url = VOLC_ASR_URL
        self.app_key = VOLC_ASR_APP_KEY
        self.access_key = VOLC_ASR_ACCESS_KEY
        self.resource_id = VOLC_ASR_RESOURCE_ID
        self.sample_rate = VOLC_ASR_SAMPLE_RATE
        self.ws = None
        self.seq = 1
        self.final_text = ""
        self.partial_text = ""

    @property
    def ready(self) -> bool:
        return bool(self.url and self.app_key and self.access_key and self.resource_id)

    async def connect(self) -> None:
        if not self.ready:
            raise VolcAsrError("Volcengine ASR is not configured")

        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Access-Key": self.access_key,
            "X-Api-App-Key": self.app_key,
        }
        try:
            self.ws = await _websocket_connect(self.url, headers=headers)
        except Exception as exc:
            raise VolcAsrError(
                "Volcengine ASR WebSocket 握手失败。"
                "如果是 HTTP 403，通常是 VOLC_ASR_APP_KEY / VOLC_ASR_ACCESS_KEY "
                "没有开通流式语音识别资源，或 VOLC_ASR_RESOURCE_ID 不属于当前账号。"
                f"原始错误: {exc}"
            ) from exc
        await self.ws.send(protocol.build_sauc_full_request(self.seq, self._start_payload()))
        self.seq += 1
        await self._recv_once()

    async def send_audio(self, audio: bytes, is_last: bool = False) -> None:
        if self.ws is None:
            raise VolcAsrError("ASR websocket is not connected")
        await self.ws.send(protocol.build_sauc_audio_request(self.seq, audio, is_last=is_last))
        if not is_last:
            self.seq += 1

    async def receive_loop(self, events: asyncio.Queue[dict[str, Any]]) -> None:
        if self.ws is None:
            raise VolcAsrError("ASR websocket is not connected")
        try:
            async for raw in self.ws:
                if not isinstance(raw, bytes):
                    continue
                message = protocol.parse_message(raw)
                if message.type == protocol.MsgType.ERROR:
                    payload = message.payload.decode("utf-8", "ignore")
                    raise VolcAsrError(f"Volcengine ASR error {message.error_code}: {payload}")

                payload = _safe_json_payload(message)
                text = extract_text(payload)
                if text:
                    self.partial_text = text
                    if is_final_payload(payload) or message.flag == protocol.MsgFlag.NEGATIVE_SEQ:
                        self.final_text = text
                    await events.put(
                        {
                            "type": "asr",
                            "text": text,
                            "final": bool(self.final_text == text),
                            "payload": payload,
                        }
                    )

                if message.flag == protocol.MsgFlag.NEGATIVE_SEQ:
                    break
        finally:
            await events.put({"type": "asr_end", "text": self.final_text or self.partial_text})

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    def _start_payload(self) -> dict[str, Any]:
        return {
            "user": {"uid": "cv_avatar"},
            "audio": {
                "format": VOLC_ASR_AUDIO_FORMAT,
                "codec": VOLC_ASR_AUDIO_CODEC,
                "rate": self.sample_rate,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False,
            },
        }

    async def _recv_once(self) -> None:
        if self.ws is None:
            return
        raw = await self.ws.recv()
        if isinstance(raw, bytes):
            message = protocol.parse_message(raw)
            if message.type == protocol.MsgType.ERROR:
                payload = message.payload.decode("utf-8", "ignore")
                raise VolcAsrError(f"Volcengine ASR error {message.error_code}: {payload}")


def extract_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in {"text", "result", "utterance", "sentence"} and isinstance(item, str):
                    candidates.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return max((item.strip() for item in candidates if item and item.strip()), key=len, default="")


def is_final_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    text = str(payload).lower()
    return any(marker in text for marker in ("definite", "final", "is_final': true", '"is_final": true'))


def _safe_json_payload(message: protocol.VolcMessage) -> Any:
    try:
        return protocol.decode_json_payload(message)
    except Exception as exc:
        logger.debug("ASR payload decode failed: %s", exc)
        return None


async def _websocket_connect(url: str, headers: dict[str, str]):
    try:
        return await websockets.connect(url, additional_headers=headers, ping_interval=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, ping_interval=None)
