from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.speech_streaming.volc_realtime import (
    VolcRealtimeDialogClient,
    VolcRealtimeDialogConfig,
    VolcRealtimeDialogError,
)

from core.tenant_voice.volc_clone import (
    VolcCloneClient,
    normalize_provider_state,
    redact_payload,
)


def write_test_wav(path: Path, seconds: int = 15) -> Path:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(b"\x00\x00" * 24000 * seconds)
    return path


class VolcCloneClientTests(unittest.TestCase):
    def test_upload_uses_o2_clone_contract(self) -> None:
        captured = {}

        def post(url, headers, body, timeout):
            captured.update(url=url, headers=headers, body=body, timeout=timeout)
            return {"code": 0, "message": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            wav = write_test_wav(Path(temp_dir) / "sample.wav")
            client = VolcCloneClient("app", "token", http_post=post)
            result = client.upload("S_voice", wav, "这是一段与音频一致的中文文本。")

        self.assertEqual(result["code"], 0)
        self.assertEqual(captured["headers"]["Resource-Id"], "seed-icl-2.0")
        self.assertEqual(captured["body"]["model_type"], 4)
        self.assertEqual(captured["body"]["source"], 2)
        self.assertEqual(captured["body"]["audios"][0]["audio_format"], "wav")

    def test_redaction_removes_audio_token_and_full_speaker(self) -> None:
        value = redact_payload(
            {
                "access_token": "secret",
                "speaker_id": "S_super_secret_voice",
                "audio_bytes": "base64",
            }
        )

        self.assertEqual(value["access_token"], "***")
        self.assertEqual(value["audio_bytes"], "***")
        self.assertNotEqual(value["speaker_id"], "S_super_secret_voice")

    def test_status_uses_status_resource_and_normalizes_legacy_code(self) -> None:
        captured = {}

        def post(url, headers, body, timeout):
            captured.update(url=url, headers=headers, body=body, timeout=timeout)
            return {"BaseResp": {"StatusCode": 0}, "status": 2}

        client = VolcCloneClient("app", "token", http_post=post)
        result = client.status("S_voice")

        self.assertEqual(
            captured["headers"]["Resource-Id"],
            "volc.megatts.voiceclone",
        )
        self.assertEqual(result["state"], "success")
        self.assertEqual(
            normalize_provider_state(
                {"Result": {"Statuses": [{"State": "Active"}]}}
            ),
            "active",
        )


class VolcRealtimeDialogClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_uses_configured_app_key_header(self) -> None:
        captured = {}

        async def connect(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("additional_headers") or {}
            raise RuntimeError("stop before network")

        client = VolcRealtimeDialogClient(
            VolcRealtimeDialogConfig(
                app_id="app-id",
                access_key="access-key",
                app_key="app-key",
            ),
            start_session_payload={},
        )

        with patch("websockets.connect", side_effect=connect):
            with self.assertRaises(VolcRealtimeDialogError):
                await client.connect()

        self.assertEqual(captured["headers"]["X-Api-App-ID"], "app-id")
        self.assertEqual(captured["headers"]["X-Api-App-Key"], "app-key")
        self.assertEqual(captured["headers"]["X-Api-Access-Key"], "access-key")

    async def test_text_query_uses_chat_text_query_event(self) -> None:
        client = VolcRealtimeDialogClient(
            VolcRealtimeDialogConfig("app", "key"),
            start_session_payload={},
        )
        client.send_event = AsyncMock()

        await client.send_text_query("你好")

        client.send_event.assert_awaited_once_with(501, {"content": "你好"})

    async def test_text_query_rejects_empty_content(self) -> None:
        client = VolcRealtimeDialogClient(
            VolcRealtimeDialogConfig("app", "key"),
            start_session_payload={},
        )

        with self.assertRaises(ValueError):
            await client.send_text_query("  ")
