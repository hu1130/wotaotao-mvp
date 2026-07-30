"""Binary protocol helpers for Volcengine speech WebSocket APIs."""

from __future__ import annotations

import gzip
import io
import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class MsgType(IntEnum):
    FULL_CLIENT_REQUEST = 0b0001
    AUDIO_ONLY_CLIENT = 0b0010
    FULL_SERVER_RESPONSE = 0b1001
    AUDIO_ONLY_SERVER = 0b1011
    ERROR = 0b1111


class MsgFlag(IntEnum):
    NO_SEQ = 0b0000
    POSITIVE_SEQ = 0b0001
    LAST_NO_SEQ = 0b0010
    NEGATIVE_SEQ = 0b0011
    WITH_EVENT = 0b0100


class Serialization(IntEnum):
    RAW = 0b0000
    JSON = 0b0001


class Compression(IntEnum):
    NONE = 0b0000
    GZIP = 0b0001


class EventType(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    SESSION_FINISHED = 152


@dataclass
class VolcMessage:
    type: int
    flag: int
    serialization: int = Serialization.JSON
    compression: int = Compression.NONE
    event: int = 0
    session_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""


def gzip_json(data: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def build_sauc_full_request(seq: int, payload: dict[str, Any]) -> bytes:
    body = gzip_json(payload)
    return _build_message(
        msg_type=MsgType.FULL_CLIENT_REQUEST,
        flag=MsgFlag.POSITIVE_SEQ,
        serialization=Serialization.JSON,
        compression=Compression.GZIP,
        sequence=seq,
        payload=body,
    )


def build_sauc_audio_request(seq: int, audio: bytes, is_last: bool) -> bytes:
    send_seq = -abs(seq) if is_last else seq
    return _build_message(
        msg_type=MsgType.AUDIO_ONLY_CLIENT,
        flag=MsgFlag.NEGATIVE_SEQ if is_last else MsgFlag.POSITIVE_SEQ,
        serialization=Serialization.JSON,
        compression=Compression.GZIP,
        sequence=send_seq,
        payload=gzip.compress(audio),
    )


def build_event_request(event: int, payload: bytes = b"{}", session_id: str = "") -> bytes:
    return _build_message(
        msg_type=MsgType.FULL_CLIENT_REQUEST,
        flag=MsgFlag.WITH_EVENT,
        serialization=Serialization.JSON,
        compression=Compression.NONE,
        event=event,
        session_id=session_id,
        payload=payload,
    )


def build_full_client_request(payload: bytes) -> bytes:
    return _build_message(
        msg_type=MsgType.FULL_CLIENT_REQUEST,
        flag=MsgFlag.NO_SEQ,
        serialization=Serialization.JSON,
        compression=Compression.NONE,
        payload=payload,
    )


def parse_message(data: bytes) -> VolcMessage:
    if len(data) < 4:
        raise ValueError("Volcengine message is too short")

    msg_type = data[1] >> 4
    flag = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    header_size = (data[0] & 0x0F) * 4
    buffer = io.BytesIO(data[header_size:])
    msg = VolcMessage(
        type=msg_type,
        flag=flag,
        serialization=serialization,
        compression=compression,
    )

    if msg_type in {
        MsgType.FULL_CLIENT_REQUEST,
        MsgType.AUDIO_ONLY_CLIENT,
        MsgType.FULL_SERVER_RESPONSE,
        MsgType.AUDIO_ONLY_SERVER,
    }:
        if flag in {MsgFlag.POSITIVE_SEQ, MsgFlag.NEGATIVE_SEQ}:
            seq = buffer.read(4)
            if seq:
                msg.sequence = struct.unpack(">i", seq)[0]
        if flag == MsgFlag.WITH_EVENT:
            event = buffer.read(4)
            if event:
                msg.event = struct.unpack(">i", event)[0]
            if msg.event not in {1, 2, 50, 51, 52}:
                session_size = buffer.read(4)
                if session_size:
                    size = struct.unpack(">I", session_size)[0]
                    if size:
                        msg.session_id = buffer.read(size).decode("utf-8", "ignore")
            if msg.event in {50, 51, 52}:
                connect_size = buffer.read(4)
                if connect_size:
                    size = struct.unpack(">I", connect_size)[0]
                    if size:
                        buffer.read(size)
    elif msg_type == MsgType.ERROR:
        code = buffer.read(4)
        if code:
            msg.error_code = struct.unpack(">I", code)[0]
    else:
        raise ValueError(f"Unsupported Volcengine message type: {msg_type}")

    size_bytes = buffer.read(4)
    if size_bytes:
        size = struct.unpack(">I", size_bytes)[0]
        msg.payload = buffer.read(size) if size else b""

    if msg.payload and msg.compression == Compression.GZIP:
        msg.payload = gzip.decompress(msg.payload)
    return msg


def decode_json_payload(msg: VolcMessage) -> Any:
    if not msg.payload:
        return None
    return json.loads(msg.payload.decode("utf-8"))


def _build_message(
    *,
    msg_type: int,
    flag: int,
    serialization: int,
    compression: int,
    payload: bytes,
    sequence: int = 0,
    event: int = 0,
    session_id: str = "",
) -> bytes:
    buffer = io.BytesIO()
    buffer.write(bytes([(1 << 4) | 1, (msg_type << 4) | flag, (serialization << 4) | compression, 0]))

    if flag == MsgFlag.WITH_EVENT:
        buffer.write(struct.pack(">i", event))
        if event not in {1, 2}:
            session_bytes = session_id.encode("utf-8")
            buffer.write(struct.pack(">I", len(session_bytes)))
            buffer.write(session_bytes)
    elif flag in {MsgFlag.POSITIVE_SEQ, MsgFlag.NEGATIVE_SEQ}:
        buffer.write(struct.pack(">i", sequence))

    buffer.write(struct.pack(">I", len(payload)))
    buffer.write(payload)
    return buffer.getvalue()
