"""Browser-facing ASR -> LLM stream -> TTS streaming pipeline."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import wave
from typing import Awaitable, Callable

from config import VOICE_PIPELINE_MAX_LLM_CHARS, VOICE_PIPELINE_SENTENCE_CHARS
from core.dialog_chat import get_dialog_chat_service
from core.speech_streaming.volc_asr import VolcAsrError, VolcStreamingAsrClient
from core.speech_streaming.volc_tts import VolcStreamingTtsClient, VolcTtsError

logger = logging.getLogger(__name__)

Sender = Callable[[dict], Awaitable[None]]


class VoicePipelineError(RuntimeError):
    pass


class VoicePipelineSession:
    def __init__(self, send_json: Sender):
        self.send_json = send_json
        self.asr = VolcStreamingAsrClient()
        self.tts = VolcStreamingTtsClient()
        self._asr_events: asyncio.Queue[dict] = asyncio.Queue()
        self._asr_task: asyncio.Task | None = None
        self._context: list[dict] = []
        self._turn_lock = asyncio.Lock()
        self._closed = False
        self._terminal_sent = False

    async def start(self) -> None:
        await self.asr.connect()
        self._asr_task = asyncio.create_task(self.asr.receive_loop(self._asr_events))
        await self.send_json({"type": "ready"})

    async def send_audio(self, audio: bytes) -> None:
        if not audio:
            return
        await self.asr.send_audio(audio, is_last=False)
        await self._drain_asr_events(block=False)

    def set_context(self, context: list[dict] | None) -> None:
        self._context = []
        for item in context or []:
            role = str(item.get("role") or "")[:20]
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                self._context.append({"role": role, "content": content[:500]})
        self._context = self._context[-6:]

    async def finish_audio(self) -> None:
        async with self._turn_lock:
            reason = "ok"
            try:
                await self.asr.send_audio(b"", is_last=True)
                final_text = await self._wait_for_asr_end()
                final_text = final_text.strip()
                if not final_text:
                    reason = "empty_asr"
                    return
                await self.send_json({"type": "asr_final", "text": final_text})
                await self._run_llm_and_tts(final_text)
            except Exception as exc:
                reason = "error"
                logger.exception("Voice pipeline turn failed: %s", exc)
                await self._send_error(str(exc))
            finally:
                await self._send_done(reason)

    async def close(self) -> None:
        self._closed = True
        if self._asr_task is not None:
            self._asr_task.cancel()
            try:
                await self._asr_task
            except asyncio.CancelledError:
                pass
        await self.asr.close()

    async def _wait_for_asr_end(self) -> str:
        text = ""
        while True:
            event = await self._asr_events.get()
            if event.get("type") == "asr":
                text = event.get("text") or text
                await self.send_json(
                    {
                        "type": "asr_partial",
                        "text": text,
                        "final": bool(event.get("final")),
                    }
                )
            elif event.get("type") == "asr_end":
                return event.get("text") or text

    async def _drain_asr_events(self, *, block: bool) -> None:
        while True:
            try:
                event = await self._asr_events.get() if block else self._asr_events.get_nowait()
            except asyncio.QueueEmpty:
                return
            if event.get("type") == "asr":
                await self.send_json(
                    {
                        "type": "asr_partial",
                        "text": event.get("text") or "",
                        "final": bool(event.get("final")),
                    }
                )
            elif event.get("type") == "asr_end":
                await self._asr_events.put(event)
                return

    async def _run_llm_and_tts(self, user_text: str) -> None:
        token_queue = stream_llm_to_async_queue(self._build_contextual_user_text(user_text))
        sentence_buffer = ""
        full_answer = ""
        sentence_index = 0
        await self.send_json({"type": "llm_start"})

        while True:
            token = await token_queue.get()
            if token is None:
                break
            full_answer += token
            sentence_buffer += token
            await self.send_json({"type": "llm_delta", "text": token})

            sentence, sentence_buffer = pop_speakable_sentence(sentence_buffer)
            if sentence:
                sentence_index += 1
                await self._synthesize_sentence(sentence, sentence_index)
            if len(full_answer) >= VOICE_PIPELINE_MAX_LLM_CHARS:
                break

        remaining = sentence_buffer.strip()
        if remaining:
            sentence_index += 1
            await self._synthesize_sentence(remaining, sentence_index)

        await self.send_json({"type": "llm_end", "text": full_answer.strip()})

    def _build_contextual_user_text(self, user_text: str) -> str:
        if not self._context:
            return user_text
        lines = ["以下是本轮语音对话的上下文。请结合上下文理解用户追问，但优先回答最后一句。"]
        for item in self._context:
            label = "用户" if item["role"] == "user" else "助手"
            lines.append(f"{label}: {item['content']}")
        lines.append(f"用户最新问题: {user_text}")
        return "\n".join(lines)

    async def _synthesize_sentence(self, text: str, index: int) -> None:
        text = normalize_tts_text(text)
        if not text:
            return
        await self.send_json(
            {"type": "tts_start", "index": index, "text": text, "mime": self.tts.mime_type}
        )
        try:
            chunks: list[bytes] = []
            async for chunk in self.tts.synthesize(text):
                if chunk:
                    chunks.append(chunk)
            audio, metadata = assemble_tts_audio(
                chunks,
                mime_type=self.tts.mime_type,
                sample_rate=self.tts.sample_rate,
            )
            if not audio:
                raise VoicePipelineError("TTS returned empty audio")
            logger.info(
                "TTS sentence audio ready: index=%s chars=%s mime=%s chunks=%s bytes=%s duration_ms=%s",
                index,
                len(text),
                self.tts.mime_type,
                len(chunks),
                len(audio),
                metadata.get("duration_ms"),
            )
            await self.send_json(
                {
                    "type": "tts_audio",
                    "index": index,
                    "text": text,
                    "mime": self.tts.mime_type,
                    "bytes": len(audio),
                    "chunkCount": len(chunks),
                    "durationMs": metadata.get("duration_ms"),
                    "audio": base64.b64encode(audio).decode("ascii"),
                }
            )
        except Exception as exc:
            logger.warning("TTS sentence failed: index=%s text=%s error=%s", index, text, exc)
            await self._send_error(f"TTS failed: {exc}", recoverable=True)
        finally:
            await self.send_json({"type": "tts_end", "index": index})

    async def _send_error(self, message: str, *, recoverable: bool = False) -> None:
        if self._closed:
            return
        await self.send_json(
            {
                "type": "error",
                "message": message,
                "recoverable": recoverable,
            }
        )

    async def _send_done(self, reason: str = "ok") -> None:
        if self._closed or self._terminal_sent:
            return
        self._terminal_sent = True
        payload = {"type": "done"}
        if reason != "ok":
            payload["reason"] = reason
        await self.send_json(payload)


def pop_speakable_sentence(buffer: str) -> tuple[str, str]:
    buffer = buffer or ""
    match = re.search(r"[。！？!?；;\n]", buffer)
    if match:
        end = match.end()
        return buffer[:end].strip(), buffer[end:]
    if len(buffer) >= VOICE_PIPELINE_SENTENCE_CHARS:
        split_at = max(buffer.rfind("，"), buffer.rfind(","), buffer.rfind(" "))
        if split_at < 12:
            split_at = len(buffer)
        return buffer[:split_at].strip(), buffer[split_at:]
    return "", buffer


def normalize_tts_text(text: str) -> str:
    text = re.sub(r"[*#`_>\[\]()]+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def assemble_tts_audio(
    chunks: list[bytes],
    *,
    mime_type: str,
    sample_rate: int,
) -> tuple[bytes, dict]:
    if not chunks:
        return b"", {"chunk_count": 0}
    if mime_type != "audio/wav":
        audio = b"".join(chunks)
        return audio, {"chunk_count": len(chunks), "bytes": len(audio)}
    try:
        return assemble_wav_audio(chunks, sample_rate=sample_rate)
    except Exception as exc:
        audio = b"".join(chunks)
        logger.warning(
            "WAV assembly failed; using raw concatenation: chunks=%s bytes=%s error=%s",
            len(chunks),
            len(audio),
            exc,
        )
        return audio, {"chunk_count": len(chunks), "bytes": len(audio), "assembly": "fallback"}


def assemble_wav_audio(chunks: list[bytes], *, sample_rate: int) -> tuple[bytes, dict]:
    pcm_parts: list[bytes] = []
    channels: int | None = None
    sample_width: int | None = None
    frame_rate: int | None = None
    wav_chunks = 0
    raw_chunks = 0

    for chunk in chunks:
        if _looks_like_wav(chunk):
            with wave.open(io.BytesIO(chunk), "rb") as reader:
                params = reader.getparams()
                if channels is None:
                    channels = params.nchannels
                    sample_width = params.sampwidth
                    frame_rate = params.framerate
                elif (
                    channels != params.nchannels
                    or sample_width != params.sampwidth
                    or frame_rate != params.framerate
                ):
                    raise VoicePipelineError(
                        "TTS WAV chunks use inconsistent audio parameters: "
                        f"expected={channels}ch/{sample_width}bytes/{frame_rate}hz "
                        f"got={params.nchannels}ch/{params.sampwidth}bytes/{params.framerate}hz"
                    )
                pcm_parts.append(reader.readframes(params.nframes))
                wav_chunks += 1
            continue

        pcm_parts.append(chunk)
        raw_chunks += 1

    if channels is None:
        channels = 1
        sample_width = 2
        frame_rate = sample_rate

    pcm = b"".join(pcm_parts)
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(frame_rate)
        writer.writeframes(pcm)

    bytes_per_second = channels * sample_width * frame_rate
    duration_ms = int(len(pcm) * 1000 / bytes_per_second) if bytes_per_second else None
    audio = output.getvalue()
    logger.debug(
        "Assembled WAV audio: chunks=%s wav_chunks=%s raw_chunks=%s pcm_bytes=%s wav_bytes=%s duration_ms=%s",
        len(chunks),
        wav_chunks,
        raw_chunks,
        len(pcm),
        len(audio),
        duration_ms,
    )
    return audio, {
        "assembly": "wav",
        "chunk_count": len(chunks),
        "wav_chunks": wav_chunks,
        "raw_chunks": raw_chunks,
        "bytes": len(audio),
        "duration_ms": duration_ms,
    }


def _looks_like_wav(chunk: bytes) -> bool:
    return len(chunk) >= 12 and chunk[:4] == b"RIFF" and chunk[8:12] == b"WAVE"


def stream_llm_to_async_queue(user_text: str) -> asyncio.Queue[str | None]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def worker() -> None:
        try:
            for token in get_dialog_chat_service().stream_reply(user_text):
                loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception as exc:
            logger.exception("LLM stream failed: %s", exc)
            loop.call_soon_threadsafe(queue.put_nowait, "对不起，我刚刚思考时出错了，请再问我一次。")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = loop.create_task(asyncio.to_thread(worker))
    task.add_done_callback(lambda item: item.exception() if item.exception() else None)
    return queue
