"""Exercise the deployed browser WebSocket voice endpoint with a PCM sample."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

import websockets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcm", type=Path)
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1/api/v1/dialog/voice-stream",
    )
    parser.add_argument("--expect-source", default="external_rag")
    parser.add_argument("--expect-empty", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--api-secret", default=os.getenv("API_SECRET", ""))
    parser.add_argument("--device-id", default="probe")
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID", "default"))
    return parser.parse_args()


def request_voice_ticket(args: argparse.Namespace) -> str:
    path = "/api/v1/dialog/voice-ticket"
    body = json.dumps({"deviceId": args.device_id}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    payload = f"POST\n{path}\n{timestamp}\n".encode() + body
    signature = hmac.new(
        args.api_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    request = Request(
        args.api_base.rstrip("/") + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": args.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        },
    )
    with urlopen(request, timeout=10) as response:
        result = json.loads(response.read())
    return str(result.get("data", {}).get("ticket") or "")


async def run(args: argparse.Namespace) -> None:
    pcm = args.pcm.read_bytes()
    if not pcm:
        raise RuntimeError("PCM input is empty")
    server_vad = asyncio.Event()
    completed = asyncio.Event()
    events: list[dict] = []
    ticket = await asyncio.to_thread(request_voice_ticket, args)
    if not ticket:
        raise RuntimeError("voice ticket response is empty")

    async with websockets.connect(args.url, max_size=None, ping_interval=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "context",
                    "items": [],
                    "metadata": {
                        "conversation_id": "browser-voice-probe",
                        "device_id": args.device_id,
                        "tenant_id": args.tenant_id,
                        "voice_ticket": ticket,
                        "person_id": "probe-user",
                        "person_name": "测试访客",
                    },
                },
                ensure_ascii=False,
            )
        )

        async def upload() -> None:
            try:
                for offset in range(0, len(pcm), 640):
                    if server_vad.is_set():
                        return
                    await ws.send(pcm[offset : offset + 640])
                    await asyncio.sleep(0.02)
                for _ in range(150):
                    if server_vad.is_set():
                        return
                    await ws.send(b"\x00" * 640)
                    await asyncio.sleep(0.02)
            except websockets.ConnectionClosed:
                return

        async def receive() -> None:
            try:
                async for raw in ws:
                    if not isinstance(raw, str):
                        continue
                    payload = json.loads(raw)
                    events.append(payload)
                    if payload.get("type") == "asr_final":
                        server_vad.set()
                    if payload.get("type") == "done":
                        completed.set()
                        return
            except websockets.ConnectionClosed:
                return

        upload_task = asyncio.create_task(upload())
        receive_task = asyncio.create_task(receive())
        await asyncio.wait_for(completed.wait(), timeout=args.timeout)
        await upload_task
        await receive_task

    sources = {
        str(item.get("ttsType") or "")
        for item in events
        if item.get("type") == "tts_audio"
    }
    audio_bytes = sum(
        int(item.get("bytes") or 0)
        for item in events
        if item.get("type") == "tts_audio"
    )
    asr = [item.get("text") for item in events if item.get("type") == "asr_final"]
    summary = {
        "asr": asr[-1] if asr else "",
        "sources": sorted(item for item in sources if item),
        "audio_bytes": audio_bytes,
        "done": completed.is_set(),
        "done_reason": next(
            (
                str(item.get("reason") or "ok")
                for item in reversed(events)
                if item.get("type") == "done"
            ),
            "",
        ),
        "errors": [
            str(item.get("message") or "")
            for item in events
            if item.get("type") == "error"
        ],
    }
    print("BROWSER_PROBE_SUMMARY=" + json.dumps(summary, ensure_ascii=False))
    if args.expect_empty:
        if summary["done_reason"] != "empty_asr" or summary["errors"]:
            raise RuntimeError(f"expected clean empty_asr, got {summary}")
        return
    if not summary["asr"]:
        raise RuntimeError("deployed endpoint did not return asr_final")
    if audio_bytes <= 44:
        raise RuntimeError("deployed endpoint did not return playable audio")
    if args.expect_source and args.expect_source not in sources:
        raise RuntimeError(
            f"expected source {args.expect_source!r}, got {sorted(sources)}"
        )


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
