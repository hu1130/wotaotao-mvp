"""Check Volcengine ASR/TTS WebSocket credentials without printing secrets."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import websockets

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import (
    VOLC_ASR_ACCESS_KEY,
    VOLC_ASR_APP_KEY,
    VOLC_ASR_RESOURCE_ID,
    VOLC_ASR_URL,
    VOLC_TTS_ACCESS_KEY,
    VOLC_TTS_APP_KEY,
    VOLC_TTS_RESOURCE_ID,
    VOLC_TTS_URL,
)
from core.speech_streaming.volc_tts import VolcStreamingTtsClient


async def check_ws(name: str, url: str, headers: dict[str, str]) -> bool:
    missing = [key for key, value in headers.items() if not value]
    if missing:
        print(f"{name}: SKIP missing {', '.join(missing)}")
        return False
    try:
        websocket = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=None,
            max_size=10 * 1024 * 1024,
        )
        await websocket.close()
        print(f"{name}: OK")
        return True
    except TypeError:
        websocket = await websockets.connect(
            url,
            extra_headers=headers,
            ping_interval=None,
            max_size=10 * 1024 * 1024,
        )
        await websocket.close()
        print(f"{name}: OK")
        return True
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__}: {str(exc).splitlines()[0]}")
        return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check Volcengine speech WebSocket auth.")
    parser.add_argument("--asr-only", action="store_true")
    parser.add_argument("--tts-only", action="store_true")
    parser.add_argument(
        "--tts-synthesis",
        action="store_true",
        help="Also synthesize a short TTS sentence to validate resource_id and voice.",
    )
    args = parser.parse_args()

    results: list[bool] = []
    if not args.tts_only:
        results.append(
            await check_ws(
                "ASR",
                VOLC_ASR_URL,
                {
                    "X-Api-Resource-Id": VOLC_ASR_RESOURCE_ID,
                    "X-Api-Request-Id": str(uuid.uuid4()),
                    "X-Api-Access-Key": VOLC_ASR_ACCESS_KEY,
                    "X-Api-App-Key": VOLC_ASR_APP_KEY,
                },
            )
        )
    if not args.asr_only:
        if args.tts_synthesis:
            results.append(await check_tts_synthesis())
        else:
            results.append(
                await check_ws(
                    "TTS",
                    VOLC_TTS_URL,
                    {
                        "X-Api-App-Key": VOLC_TTS_APP_KEY,
                        "X-Api-Access-Key": VOLC_TTS_ACCESS_KEY,
                        "X-Api-Resource-Id": VOLC_TTS_RESOURCE_ID,
                        "X-Api-Connect-Id": str(uuid.uuid4()),
                    },
                )
            )
    return 0 if all(results) else 1


async def check_tts_synthesis() -> bool:
    try:
        chunk_count = 0
        byte_count = 0
        async for chunk in VolcStreamingTtsClient().synthesize("你好"):
            chunk_count += 1
            byte_count += len(chunk)
            if byte_count > 0:
                break
        if byte_count <= 0:
            print("TTS synthesis: FAIL empty audio")
            return False
        print(f"TTS synthesis: OK chunks={chunk_count} bytes={byte_count}")
        return True
    except Exception as exc:
        print(f"TTS synthesis: FAIL {type(exc).__name__}: {str(exc).splitlines()[0]}")
        return False


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
