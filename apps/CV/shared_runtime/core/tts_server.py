import asyncio
import argparse
import base64
import json
import os
import random
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SERVER_DIR = os.path.join(os.path.dirname(ROOT_DIR), "server_deploy")
if os.path.isdir(SERVER_DIR) and SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.fixed_tts import FixedTtsClient
from core.tts_texts import TTS_TEXTS
from config import REALTIME_DIALOG_OUTPUT_SAMPLE_RATE


class _RawTtsRequest:
    def __init__(self, text: str, voice: str = "", tenant_id: str = "") -> None:
        self.event_type = "raw"
        self.text = text
        self.voice = voice
        self.tenant_id = tenant_id


class _TypedTtsRequest(_RawTtsRequest):
    def __init__(
        self,
        *,
        event_type: str,
        text: str,
        voice: str = "",
        tenant_id: str = "",
    ) -> None:
        super().__init__(text, voice=voice, tenant_id=tenant_id)
        self.event_type = event_type


async def _generate(
    text: str,
    output_path: str,
    voice: str | None = None,
    *,
    tenant_id: str = "",
    event_type: str = "raw",
) -> None:
    request = _TypedTtsRequest(
        event_type=event_type,
        text=text,
        voice=voice or "",
        tenant_id=tenant_id,
    )
    tmp_path = f"{output_path}.tmp"
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        await FixedTtsClient(tenant_id=tenant_id or None).synthesize_to_file_async(
            request,
            tmp_path,
        )
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) <= 0:
            raise RuntimeError("TTS generated empty audio file")
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _write_ndjson(payload: dict) -> None:
    sys.stdout.buffer.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    sys.stdout.buffer.flush()


async def _stream_raw(
    text: str,
    voice: str | None = None,
    *,
    tenant_id: str = "",
) -> None:
    request = _RawTtsRequest(text=text, voice=voice or "", tenant_id=tenant_id)
    sample_rate = REALTIME_DIALOG_OUTPUT_SAMPLE_RATE
    total_bytes = 0
    _write_ndjson(
        {
            "type": "start",
            "format": "pcm_s16le",
            "sampleRate": sample_rate,
            "channels": 1,
            "bitsPerSample": 16,
        }
    )
    async for chunk in FixedTtsClient(tenant_id=tenant_id or None).stream_audio_chunks_async(
        request
    ):
        total_bytes += len(chunk)
        _write_ndjson(
            {
                "type": "audio",
                "format": "pcm_s16le",
                "sampleRate": sample_rate,
                "bytes": len(chunk),
                "audio": base64.b64encode(chunk).decode("ascii"),
            }
        )
    duration_ms = int(total_bytes / max(1, sample_rate * 2) * 1000)
    _write_ndjson({"type": "done", "bytes": total_bytes, "durationMs": duration_ms})


def pick_text(
    name: str,
    tts_type: str,
    variant: int | None = None,
    *,
    model_key: str = "",
) -> str:
    candidates = _event_candidates(tts_type, model_key=model_key)
    if variant is None:
        template = random.choice(candidates)
    else:
        template = candidates[variant % len(candidates)]
    return template.format(name)


def _event_candidates(tts_type: str, *, model_key: str = "") -> list[str]:
    model_texts = TTS_TEXTS.get(model_key) if model_key else None
    if not isinstance(model_texts, dict):
        for value in TTS_TEXTS.values():
            if isinstance(value, dict):
                model_texts = value
                break
    if not isinstance(model_texts, dict):
        return ["{}"]
    candidates = model_texts.get(tts_type)
    if not isinstance(candidates, list) or not candidates:
        return ["{}"]
    return candidates


def _manifest_counts() -> dict[str, int]:
    model_texts = None
    for value in TTS_TEXTS.values():
        if isinstance(value, dict):
            model_texts = value
            break
    if not isinstance(model_texts, dict):
        return {}
    return {
        key: len(value)
        for key, value in model_texts.items()
        if isinstance(value, list)
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true")
    parser.add_argument("--print-text", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("args", nargs="*")
    parse_intermixed = getattr(parser, "parse_intermixed_args", None)
    if callable(parse_intermixed):
        return parse_intermixed(argv)
    return parser.parse_args(argv)


if __name__ == "__main__":
    parsed = _parse_args(sys.argv[1:])
    if parsed.print_manifest:
        print(json.dumps(_manifest_counts(), ensure_ascii=False))
        sys.exit(0)

    if parsed.raw:
        if parsed.stream:
            if len(parsed.args) < 1:
                print("usage: tts_server.py --raw --stream <text> [voice]", file=sys.stderr)
                sys.exit(2)
            text = parsed.args[0].strip()
            voice = parsed.args[1] if len(parsed.args) > 1 else None
            asyncio.run(_stream_raw(text, voice, tenant_id=parsed.tenant_id))
            sys.exit(0)
        if len(parsed.args) < 2:
            print("usage: tts_server.py --raw <text> <output_path> [voice]", file=sys.stderr)
            sys.exit(2)
        text = parsed.args[0].strip()
        output_path = parsed.args[1]
        voice = parsed.args[2] if len(parsed.args) > 2 else None
        asyncio.run(_generate(text, output_path, voice, tenant_id=parsed.tenant_id))
        sys.exit(0)

    if parsed.print_text:
        if len(parsed.args) < 2:
            print("usage: tts_server.py <name> <type> --print-text [variant]", file=sys.stderr)
            sys.exit(2)
        name = parsed.args[0]
        tts_type = parsed.args[1]
        variant = int(parsed.args[2]) if len(parsed.args) > 2 else None
        print(pick_text(name, tts_type, variant))
        sys.exit(0)

    if len(parsed.args) < 3:
        print("usage: tts_server.py <name> <type> <output_path> [variant] [voice]", file=sys.stderr)
        sys.exit(2)

    name = parsed.args[0]
    tts_type = parsed.args[1]
    output_path = parsed.args[2]
    variant = int(parsed.args[3]) if len(parsed.args) > 3 else None
    voice = parsed.args[4] if len(parsed.args) > 4 else None

    text = pick_text(name, tts_type, variant)
    if output_path == "--print-text":
        print(text)
        sys.exit(0)

    asyncio.run(
        _generate(
            text,
            output_path,
            voice,
            tenant_id=parsed.tenant_id,
            event_type=tts_type,
        )
    )
