"""Inspect, prepare, train and probe an authorized O2.0 cloned voice."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    REALTIME_DIALOG_ACCESS_KEY,
    REALTIME_DIALOG_APP_KEY,
    REALTIME_DIALOG_APP_ID,
    REALTIME_DIALOG_BASE_URL,
    REALTIME_DIALOG_RESOURCE_ID,
)
from core.speech_streaming.pipeline import assemble_wav_audio
from core.speech_streaming.volc_asr import VolcStreamingAsrClient
from core.speech_streaming.volc_realtime import (
    VolcRealtimeDialogClient,
    VolcRealtimeDialogConfig,
)
from core.tenant_voice.audio import (
    inspect_audio,
    inspection_payload,
    prepare_candidates,
    convert_to_pcm16k,
)
from core.tenant_voice.service import mask_speaker_id
from core.tenant_voice.volc_clone import VolcCloneClient, redact_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="O2.0 克隆音色工程工具")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="检查音频元数据和质量")
    inspect.add_argument("--input", required=True)

    prepare = commands.add_parser("prepare", help="生成三个训练候选（建议 10-15 秒）")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--output-dir", required=True)
    prepare.add_argument("--segment-seconds", type=float, default=14.0)

    transcribe = commands.add_parser("transcribe", help="用流式 ASR 生成训练逐字稿草稿")
    transcribe.add_argument("--input", required=True)
    transcribe.add_argument("--output", required=True)

    train = commands.add_parser("train", help="上传人工确认文本的 WAV 训练音色")
    train.add_argument("--input", required=True)
    train.add_argument("--speaker-id", required=True)
    train.add_argument("--transcript-file", required=True)

    status = commands.add_parser("status", help="查询供应商训练状态")
    status.add_argument("--speaker-id", required=True)

    probe = commands.add_parser("probe", help="用 O2.0 端到端链路生成试听 WAV")
    probe.add_argument("--speaker-id", required=True)
    probe.add_argument("--output", required=True)
    probe.add_argument("--text", default="你好呀，我是公司的前台助手，很高兴认识你。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "inspect":
        _print({"ok": True, "inspection": inspection_payload(inspect_audio(args.input))})
        return 0
    if args.command == "prepare":
        candidates = prepare_candidates(
            args.input,
            args.output_dir,
            segment_seconds=args.segment_seconds,
        )
        _print(
            {
                "ok": True,
                "candidates": [inspection_payload(item) for item in candidates],
                "notice": "请逐个试听，并为选中的 WAV 准备逐字匹配文本后再训练",
            }
        )
        return 0
    if args.command == "transcribe":
        result = asyncio.run(_transcribe(Path(args.input), Path(args.output)))
        _print(result)
        return 0
    if args.command == "train":
        transcript = Path(args.transcript_file).read_text(encoding="utf-8").strip()
        result = VolcCloneClient().upload(args.speaker_id, args.input, transcript)
        _print(
            {
                "ok": True,
                "speakerIdMasked": mask_speaker_id(args.speaker_id),
                "provider": redact_payload(result),
            }
        )
        return 0
    if args.command == "status":
        result = VolcCloneClient().status(args.speaker_id)
        _print(
            {
                "ok": True,
                "speakerIdMasked": mask_speaker_id(args.speaker_id),
                "state": result["state"],
                "provider": redact_payload(result["provider"]),
            }
        )
        return 0

    result = asyncio.run(_probe(args.speaker_id, args.text, Path(args.output)))
    _print(result)
    return 0


async def _probe(speaker_id: str, text: str, output: Path) -> dict:
    if not speaker_id.startswith("S_"):
        raise ValueError("speaker_id must start with S_")
    config = VolcRealtimeDialogConfig(
        app_id=REALTIME_DIALOG_APP_ID,
        app_key=REALTIME_DIALOG_APP_KEY,
        access_key=REALTIME_DIALOG_ACCESS_KEY,
        base_url=REALTIME_DIALOG_BASE_URL,
        resource_id=REALTIME_DIALOG_RESOURCE_ID,
    )
    payload = {
        "asr": {"extra": {"enable_custom_vad": True, "end_smooth_window_ms": 1500}},
        "tts": {
            "speaker": speaker_id,
            "extra": {"tts_2.0_model": "expressive"},
            "audio_config": {
                "channel": 1,
                "format": "pcm_s16le",
                "sample_rate": 24000,
                "speech_rate": 0,
                "loudness_rate": 0,
            },
        },
        "dialog": {
            "bot_name": "前台小助手",
            "system_role": "你是公司前台数字人。",
            "speaking_style": "自然、简短、像真人聊天。",
            "extra": {
                "strict_audit": False,
                "input_mod": "keep_alive",
                "enable_loudness_norm": True,
                "model": "1.2.1.1",
            },
        },
    }
    client = VolcRealtimeDialogClient(config, start_session_payload=payload)
    chunks: list[bytes] = []
    started = False
    ended = False
    try:
        await client.connect()
        # ChatTTSText/500 is only legal after ASREnded in a user turn. A probe
        # has no microphone turn, so use ChatTextQuery/501 to make the model
        # synthesize a normal reply with the configured cloned speaker.
        query = f'请只回复以下引号内的内容，不要增加其他文字：“{text.strip()}”'
        await client.send_text_query(query)
        while not ended:
            response = await asyncio.wait_for(client.receive(), timeout=30.0)
            event = int(response.get("event") or 0)
            if event == 350:
                started = True
            elif event == 352 and isinstance(response.get("payload_msg"), bytes):
                chunks.append(response["payload_msg"])
            elif event == 359:
                ended = True
    finally:
        await client.close()
    if not started or not ended or not chunks:
        raise RuntimeError("clone probe did not complete 350 -> 352 -> 359")
    audio, metadata = assemble_wav_audio(chunks, sample_rate=24000)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio)
    passed_at = datetime.now().isoformat(timespec="seconds")
    return {
        "ok": True,
        "speakerIdMasked": mask_speaker_id(speaker_id),
        "probePassedAt": passed_at,
        "output": str(output),
        "audio": metadata,
        "next": "将 probePassedAt 传给 tenant_voice_admin.py register",
    }


async def _transcribe(source: Path, output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="voice-clone-asr-") as temp_dir:
        pcm_path = convert_to_pcm16k(source, Path(temp_dir) / "input.pcm")
        pcm = pcm_path.read_bytes()
    client = VolcStreamingAsrClient()
    events: asyncio.Queue[dict] = asyncio.Queue()
    receiver = None
    try:
        await client.connect()
        receiver = asyncio.create_task(client.receive_loop(events))
        for offset in range(0, len(pcm), 640):
            await client.send_audio(pcm[offset : offset + 640])
            await asyncio.sleep(0.02)
        await client.send_audio(b"", is_last=True)
        transcript = ""
        while True:
            event = await asyncio.wait_for(events.get(), timeout=15.0)
            if event.get("type") == "asr":
                transcript = str(event.get("text") or transcript).strip()
            if event.get("type") == "asr_end":
                transcript = str(event.get("text") or transcript).strip()
                break
    finally:
        if receiver is not None and not receiver.done():
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        await client.close()
    if not transcript:
        raise RuntimeError("streaming ASR returned an empty transcript")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(transcript + "\n", encoding="utf-8")
    return {
        "ok": True,
        "transcript": transcript,
        "chars": len(transcript),
        "output": str(output),
        "notice": "训练接口会继续执行 WER 校验；高质量场景仍建议人工核对",
    }


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
