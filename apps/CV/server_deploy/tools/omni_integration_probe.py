"""Feed a PCM sample through the browser-facing Omni backend for diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.speech_streaming.omni import OmniVoicePipelineSession


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcm", type=Path, help="16kHz mono signed-16 little-endian PCM")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--expect-source", choices=("external_rag", "default", "chat_tts_text"))
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    events: list[dict] = []
    audio_bytes = 0

    async def sender(payload: dict) -> None:
        nonlocal audio_bytes
        events.append(payload)
        if payload.get("type") == "tts_audio":
            audio_bytes += int(payload.get("bytes") or 0)
        safe = {key: value for key, value in payload.items() if key != "audio"}
        print("BROWSER_EVENT=" + json.dumps(safe, ensure_ascii=False), flush=True)

    pcm = args.pcm.read_bytes()
    if not pcm:
        raise RuntimeError("PCM input is empty")

    session = OmniVoicePipelineSession(sender)
    session.set_metadata(
        {
            "tenant_id": args.tenant_id,
            "conversation_id": "omni-integration-probe",
            "device_id": "probe",
        }
    )
    session.set_person_context(
        person_id="probe-user",
        person_name="测试访客",
        verified=True,
    )
    try:
        await session.start()
        for offset in range(0, len(pcm), 640):
            if session._input_ended:
                break
            await session.send_audio(pcm[offset : offset + 640])
            await asyncio.sleep(0.02)
        for _ in range(150):
            if session._input_ended:
                break
            await session.send_audio(b"\x00" * 640)
            await asyncio.sleep(0.02)
        await asyncio.wait_for(session._finished.wait(), timeout=args.timeout)
    finally:
        await session.close()

    asr_texts = [item.get("text") for item in events if item.get("type") == "asr_final"]
    sources = {
        str(item.get("ttsType") or "")
        for item in events
        if item.get("type") == "tts_audio"
    }
    print(
        "PROBE_SUMMARY="
        + json.dumps(
            {
                "asr": asr_texts[-1] if asr_texts else "",
                "sources": sorted(item for item in sources if item),
                "audio_bytes": audio_bytes,
                "done": any(item.get("type") == "done" for item in events),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if not asr_texts:
        raise RuntimeError("probe did not receive asr_final")
    if audio_bytes <= 44:
        raise RuntimeError("probe did not receive playable audio")
    if args.expect_source and args.expect_source not in sources:
        raise RuntimeError(
            f"probe expected source {args.expect_source!r}, got {sorted(sources)}"
        )


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
