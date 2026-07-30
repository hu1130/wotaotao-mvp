from __future__ import annotations

import unittest
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_fixed_tts_module():
    repo_root = Path(__file__).resolve().parents[2]
    server_path = str(repo_root / "server_deploy")
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = [str(repo_root / "shared_runtime" / "core")]
    speech_pkg = types.ModuleType("core.speech_streaming")
    speech_pkg.__path__ = [
        str(repo_root / "shared_runtime" / "core" / "speech_streaming")
    ]
    realtime_module = types.ModuleType("core.speech_streaming.volc_realtime")

    class VolcRealtimeDialogClient:
        pass

    class VolcRealtimeDialogConfig:
        pass

    realtime_module.VolcRealtimeDialogClient = VolcRealtimeDialogClient
    realtime_module.VolcRealtimeDialogConfig = VolcRealtimeDialogConfig
    sys.modules.setdefault("core", core_pkg)
    sys.modules.setdefault("core.speech_streaming", speech_pkg)
    sys.modules["core.speech_streaming.volc_realtime"] = realtime_module
    spec = importlib.util.spec_from_file_location(
        "fixed_tts_under_test",
        repo_root / "shared_runtime" / "core" / "fixed_tts.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixed_tts = _load_fixed_tts_module()
FixedTtsClient = fixed_tts.FixedTtsClient
FixedTtsVoice = fixed_tts.FixedTtsVoice


class FixedTtsVoiceTests(unittest.TestCase):
    def test_explicit_bigtts_voice_bypasses_tenant_clone_profile(self) -> None:
        client = FixedTtsClient(tenant_id="tenant-a", provider="volc")
        request = SimpleNamespace(
            tenant_id="tenant-a",
            voice="zh_male_yunzhou_jupiter_bigtts",
        )

        with patch(
            "fixed_tts_under_test.REALTIME_DIALOG_APP_ID",
            "app-id",
        ), patch(
            "fixed_tts_under_test.REALTIME_DIALOG_ACCESS_KEY",
            "access-key",
        ), patch.object(
            client,
            "_resolve_tenant_voice",
            side_effect=AssertionError("explicit BigTTS voice must be honored"),
        ):
            voice = client.resolve_request(request)

        self.assertEqual(voice.provider, "volc")
        self.assertEqual(voice.speaker_id, "zh_male_yunzhou_jupiter_bigtts")
        self.assertFalse(voice.clone_enabled)
        self.assertEqual(voice.tts_2_0_model, "")

    def test_edge_voice_name_still_uses_tenant_voice_in_volc_mode(self) -> None:
        client = FixedTtsClient(tenant_id="tenant-a", provider="volc")
        request = SimpleNamespace(
            tenant_id="tenant-a",
            voice="zh-CN-XiaoxiaoNeural",
        )

        with patch(
            "fixed_tts_under_test.REALTIME_DIALOG_APP_ID",
            "app-id",
        ), patch(
            "fixed_tts_under_test.REALTIME_DIALOG_ACCESS_KEY",
            "access-key",
        ), patch.object(
            client,
            "_resolve_tenant_voice",
            return_value=FixedTtsVoice(
                provider="volc",
                tenant_id="tenant-a",
                speaker_id="tenant-speaker",
            ),
        ) as resolve_tenant_voice:
            voice = client.resolve_request(request)

        resolve_tenant_voice.assert_called_once_with("tenant-a")
        self.assertEqual(voice.provider, "volc")
        self.assertEqual(voice.speaker_id, "tenant-speaker")


if __name__ == "__main__":
    unittest.main()
