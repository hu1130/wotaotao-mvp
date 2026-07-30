"""Async transport for Volcengine's end-to-end realtime dialog API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from core import realtime_dialog_protocol as protocol


logger = logging.getLogger(__name__)
DEFAULT_REALTIME_DIALOG_APP_KEY = "PlgvMymc7f3tQnJ6"


class VolcRealtimeDialogError(RuntimeError):
    """Raised when the Volcengine realtime dialog transport fails."""


@dataclass(frozen=True)
class VolcRealtimeDialogConfig:
    app_id: str
    access_key: str
    app_key: str = ""
    base_url: str = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
    resource_id: str = "volc.speech.dialog"
    connect_timeout_seconds: float = 15.0
    ping_interval_seconds: float = 20.0
    ping_timeout_seconds: float = 10.0
    close_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.app_key:
            object.__setattr__(self, "app_key", DEFAULT_REALTIME_DIALOG_APP_KEY)

    @property
    def ready(self) -> bool:
        return bool(
            self.app_id.strip()
            and self.app_key.strip()
            and self.access_key.strip()
        )


class VolcRealtimeDialogClient:
    """Owns one gateway connection and one realtime dialog session."""

    def __init__(
        self,
        config: VolcRealtimeDialogConfig,
        *,
        start_session_payload: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self.start_session_payload = start_session_payload
        self.session_id = session_id or str(uuid.uuid4())
        self.ws = None
        self.logid = ""
        self.dialog_id = ""
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._session_started = False

    async def connect(self) -> None:
        if not self.config.ready:
            raise VolcRealtimeDialogError("realtime dialog credentials are not configured")

        import websockets

        connect_id = str(uuid.uuid4())
        headers = {
            "X-Api-App-ID": self.config.app_id,
            "X-Api-Access-Key": self.config.access_key,
            "X-Api-Resource-Id": self.config.resource_id,
            "X-Api-App-Key": self.config.app_key,
            "X-Api-Connect-Id": connect_id,
        }
        connect_kwargs = {
            "ping_interval": self.config.ping_interval_seconds,
            "ping_timeout": self.config.ping_timeout_seconds,
            "close_timeout": self.config.close_timeout_seconds,
            "open_timeout": self.config.connect_timeout_seconds,
            "max_size": None,
        }
        logger.info(
            "Omni WebSocket 握手开始: resource=%s app_id=%s app_key=%s connect_id=%s",
            self.config.resource_id,
            _mask_value(self.config.app_id),
            _mask_value(self.config.app_key),
            connect_id,
        )
        try:
            try:
                self.ws = await websockets.connect(
                    self.config.base_url,
                    additional_headers=headers,
                    **connect_kwargs,
                )
            except TypeError:
                self.ws = await websockets.connect(
                    self.config.base_url,
                    extra_headers=headers,
                    **connect_kwargs,
                )
        except Exception as exc:
            raise VolcRealtimeDialogError(
                "realtime dialog websocket handshake failed: "
                f"resource={self.config.resource_id} "
                f"app_id={_mask_value(self.config.app_id)} "
                f"app_key={_mask_value(self.config.app_key)} "
                f"error={exc}"
            ) from exc

        response_headers = getattr(self.ws, "response_headers", None)
        if response_headers is None and getattr(self.ws, "response", None) is not None:
            response_headers = getattr(self.ws.response, "headers", None)
        self.logid = response_headers.get("X-Tt-Logid", "") if response_headers else ""

        connection_response = await self._send_and_receive(1, {})
        self._expect_event(connection_response, 50, "StartConnection")
        self._connected = True

        session_response = await self._send_and_receive(
            100,
            self.start_session_payload,
            with_session=True,
        )
        self._expect_event(session_response, 150, "StartSession")
        payload = session_response.get("payload_msg")
        if isinstance(payload, dict):
            self.dialog_id = str(payload.get("dialog_id") or "")
        self._session_started = True
        logger.info(
            "Omni 会话建立成功: session=%s dialog=%s logid=%s",
            self.session_id,
            self.dialog_id or "(new)",
            self.logid or "(missing)",
        )

    async def send_audio(self, audio: bytes) -> None:
        if not audio:
            return
        self._require_session()
        request = protocol.generate_header(
            message_type=protocol.CLIENT_AUDIO_ONLY_REQUEST,
            serial_method=protocol.NO_SERIALIZATION,
            compression_type=protocol.NO_COMPRESSION,
        )
        request.extend(int(200).to_bytes(4, "big"))
        self._append_session_id(request)
        request.extend(len(audio).to_bytes(4, "big"))
        request.extend(audio)
        await self._send(request)

    async def send_external_rag(self, external_rag: str) -> None:
        await self.send_event(502, {"external_rag": external_rag})

    async def send_chat_tts_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        chunks = [text[index : index + 80] for index in range(0, len(text), 80)]
        for index, chunk in enumerate(chunks):
            await self.send_event(
                500,
                {"start": index == 0, "content": chunk, "end": False},
            )
        await self.send_event(500, {"start": False, "content": "", "end": True})

    async def send_text_query(self, text: str) -> None:
        """Start a normal model turn from text input (ChatTextQuery/501)."""

        text = (text or "").strip()
        if not text:
            raise ValueError("text query must not be empty")
        await self.send_event(501, {"content": text})

    async def send_end_asr(self) -> None:
        await self.send_event(400, {})

    async def send_client_interrupt(self) -> None:
        await self.send_event(515, {})

    async def send_conversation_truncate(
        self,
        reply_id: str,
        audio_end_ms: int,
    ) -> None:
        reply_id = str(reply_id or "").strip()
        if not reply_id:
            raise ValueError("reply_id is required for conversation truncation")
        await self.send_event(
            513,
            {
                "item_id": reply_id,
                "audio_end_ms": max(0, int(audio_end_ms)),
            },
        )

    async def send_event(self, event: int, payload: dict[str, Any]) -> None:
        self._require_session()
        request = self._build_full_event(event, payload, with_session=True)
        await self._send(request)

    async def receive(self) -> dict[str, Any]:
        if self.ws is None:
            raise VolcRealtimeDialogError("realtime dialog websocket is not connected")
        try:
            response = protocol.parse_response(await self.ws.recv())
        except Exception as exc:
            raise VolcRealtimeDialogError(f"realtime dialog receive failed: {exc}") from exc
        if response.get("message_type") == "SERVER_ERROR":
            raise VolcRealtimeDialogError(self._error_message(response))
        return response

    async def finish_session(self) -> None:
        if not self._session_started:
            return
        await self._send(self._build_full_event(102, {}, with_session=True))
        self._session_started = False

    async def finish_connection(self) -> None:
        if not self._connected:
            return
        await self._send(self._build_full_event(2, {}, with_session=False))
        self._connected = False

    async def close(self) -> None:
        ws = self.ws
        if ws is None:
            return
        try:
            await self.finish_session()
            await self.finish_connection()
        except Exception as exc:
            logger.debug("Omni 会话关闭事件发送失败: %s", exc)
        finally:
            self._session_started = False
            self._connected = False
            self.ws = None
            try:
                await ws.close()
            except Exception:
                pass

    async def _send_and_receive(
        self,
        event: int,
        payload: dict[str, Any],
        *,
        with_session: bool = False,
    ) -> dict[str, Any]:
        await self._send(self._build_full_event(event, payload, with_session=with_session))
        if self.ws is None:
            raise VolcRealtimeDialogError("realtime dialog websocket closed during handshake")
        try:
            raw = await asyncio.wait_for(
                self.ws.recv(),
                timeout=self.config.connect_timeout_seconds,
            )
        except Exception as exc:
            raise VolcRealtimeDialogError(f"realtime dialog handshake failed: {exc}") from exc
        response = protocol.parse_response(raw)
        if response.get("message_type") == "SERVER_ERROR":
            raise VolcRealtimeDialogError(self._error_message(response))
        return response

    async def _send(self, request: bytes | bytearray) -> None:
        if self.ws is None:
            raise VolcRealtimeDialogError("realtime dialog websocket is not connected")
        async with self._send_lock:
            try:
                await self.ws.send(request)
            except Exception as exc:
                raise VolcRealtimeDialogError(f"realtime dialog send failed: {exc}") from exc

    def _build_full_event(
        self,
        event: int,
        payload: dict[str, Any],
        *,
        with_session: bool,
    ) -> bytearray:
        request = protocol.generate_header()
        request.extend(int(event).to_bytes(4, "big"))
        if with_session:
            self._append_session_id(request)
        payload_bytes = protocol.encode_json_payload(payload)
        request.extend(len(payload_bytes).to_bytes(4, "big"))
        request.extend(payload_bytes)
        return request

    def _append_session_id(self, request: bytearray) -> None:
        session_bytes = self.session_id.encode("utf-8")
        request.extend(len(session_bytes).to_bytes(4, "big"))
        request.extend(session_bytes)

    def _require_session(self) -> None:
        if not self._session_started or self.ws is None:
            raise VolcRealtimeDialogError("realtime dialog session is not started")

    @staticmethod
    def _expect_event(response: dict[str, Any], expected: int, operation: str) -> None:
        if response.get("event") == expected:
            return
        raise VolcRealtimeDialogError(
            f"{operation} failed: event={response.get('event')} "
            f"payload={response.get('payload_msg')}"
        )

    @staticmethod
    def _error_message(response: dict[str, Any]) -> str:
        return (
            "realtime dialog server error: "
            f"code={response.get('code')} payload={response.get('payload_msg')}"
        )


def _mask_value(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "(empty)"
    if len(text) <= 6:
        return text[:2] + "***"
    return text[:3] + "***" + text[-2:]
