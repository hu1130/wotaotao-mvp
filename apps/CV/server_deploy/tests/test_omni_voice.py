from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from core.dialog_intent_router import (
    DialogIntentRoute,
    ROUTE_CHAT,
    ROUTE_KNOWLEDGE,
)
from core.dialog_wake_name import WakeNameResult
from core.dialog_silence import get_dialog_silence_state_store
from core.dialog_actions import (
    ACTION_ADJUST_SYSTEM_VOLUME,
    DialogActionExecution,
    DialogActionProposal,
)
from core.speech_streaming.omni import (
    ExternalRagTimeout,
    TTS_TYPE_DEFAULT,
    TTS_TYPE_EXTERNAL_RAG,
    TTS_TYPE_CHAT_TEXT,
    OmniVoicePipelineSession,
)
from core.tenant_voice.models import OmniSessionSettings


async def _discard(_payload: dict) -> None:
    return None


def _wake_name_miss(text: str = "") -> WakeNameResult:
    return WakeNameResult(
        called=False,
        wake_only=False,
        assistant_name="叮当",
        matched_alias="",
        original_text=text,
        command_text=text,
    )


async def _echo_scene_reply(canonical_text: str, **_kwargs) -> str:
    return canonical_text


class OmniVoicePipelineSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = OmniVoicePipelineSession(_discard)
        self.session._generate_scene_reply = AsyncMock(side_effect=_echo_scene_reply)
        self.session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="叮当",
                wake_aliases=("叮当", "小叮当"),
            )
        )
        self.session._resolve_persona_settings = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="叮当",
                wake_aliases=("叮当", "小叮当"),
                version=0,
                system_role="你是前台数字人。",
                speaking_style="自然简短。",
            )
        )

    def _mock_person_context_external_success(self):
        transport = SimpleNamespace(
            send_external_rag=AsyncMock(),
            send_client_interrupt=AsyncMock(),
        )
        self.session.transport = transport
        self.session._generate_scene_reply = AsyncMock(
            side_effect=AssertionError(
                "Omni person context must use Volc external RAG"
            )
        )
        self.session._synthesize_sentence = AsyncMock(
            side_effect=AssertionError(
                "Omni person context must not pre-synthesize scene text"
            )
        )
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )

        async def external_response(sender) -> float:
            await sender()
            self.session._commit_external_response()
            return 1.0

        self.session._request_external_rag_response = AsyncMock(
            side_effect=external_response
        )
        self.session._complete_turn = AsyncMock()
        return transport

    def _mock_external_rag_success(self):
        transport = SimpleNamespace(
            send_external_rag=AsyncMock(),
            send_client_interrupt=AsyncMock(),
        )
        self.session.transport = transport
        self.session._generate_scene_reply = AsyncMock(
            side_effect=AssertionError("Omni control feedback must not use DashScope")
        )
        self.session._synthesize_sentence = AsyncMock(
            side_effect=AssertionError(
                "Omni control feedback must use upstream Omni TTS"
            )
        )
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )

        async def external_response(sender) -> float:
            await sender()
            self.session._answer_parts.append("好，我先安静一会儿，喊小鹿我再回来。")
            self.session._commit_external_response()
            return 1.0

        self.session._request_external_rag_response = AsyncMock(
            side_effect=external_response
        )
        self.session._expire_external_generation = AsyncMock()
        return transport

    def test_default_tts_end_signal_is_per_turn(self) -> None:
        async def scenario() -> None:
            self.assertFalse(self.session._default_tts_ended.is_set())
            self.session._response_types_seen.add(TTS_TYPE_DEFAULT)
            await self.session._on_tts_ended({})
            self.assertTrue(self.session._default_tts_ended.is_set())

            self.session._reset_turn_state()

            self.assertFalse(self.session._default_tts_ended.is_set())

        asyncio.run(scenario())

    def test_audio_after_server_vad_is_not_forwarded_into_current_turn(self) -> None:
        transport = SimpleNamespace(send_audio=AsyncMock())
        self.session.transport = transport
        self.session._started = True
        self.session._turn_active = True
        self.session._input_ended = True

        asyncio.run(self.session.send_audio(b"\x01" * 640))

        transport.send_audio.assert_not_awaited()
        self.assertEqual(self.session._late_audio_chunks, 1)
        self.assertEqual(self.session._late_audio_bytes, 640)

    def test_dialog_silence_interrupts_omni_default_generation(self) -> None:
        transport = SimpleNamespace(send_client_interrupt=AsyncMock())
        self.session.transport = transport
        self.session.tenant_id = "tenant-silence"
        self.session.device_id = "frontdesk-silence"
        self.session._response_types_seen.add(TTS_TYPE_DEFAULT)
        self.session._pending_default_sentences = [
            ("默认回答不能播放。", [b"default-audio"], "default-reply")
        ]
        self.session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="小鹿",
                wake_aliases=("小鹿", "鹿鹿"),
            )
        )
        self.session._speak_scene_response = AsyncMock(
            return_value="我先安静一下，需要时喊我就好。"
        )

        try:
            result = asyncio.run(
                self.session._handle_dialog_silence_control("别说话了")
            )
        finally:
            get_dialog_silence_state_store().clear(
                "tenant-silence",
                "frontdesk-silence",
            )

        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "dialog_silenced")
        transport.send_client_interrupt.assert_awaited_once()
        self.assertEqual(self.session._pending_default_sentences, [])
        self.assertEqual(
            self.session._recycle_transport_reason,
            "dialog_silence_mute_interrupted",
        )
        self.session._speak_scene_response.assert_awaited_once()

    def test_dialog_silenced_followup_interrupts_and_drops_default_audio(self) -> None:
        transport = SimpleNamespace(send_client_interrupt=AsyncMock())
        self.session.transport = transport
        self.session.tenant_id = "tenant-silence"
        self.session.device_id = "frontdesk-silence-followup"
        self.session._dialog_silenced = True
        self.session._dialog_silence_status_text = "静音中，喊小鹿唤醒我"
        self.session._current_tts_type = TTS_TYPE_DEFAULT
        self.session._current_tts_text = "你好呀。"
        self.session._current_reply_id = "default-reply"
        self.session._current_audio_chunks = [b"default-audio"]
        self.session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="小鹿",
                wake_aliases=("小鹿", "鹿鹿"),
            )
        )
        self.session._speak_scene_response = AsyncMock(
            return_value="我先安静一下，需要时喊我就好。"
        )

        try:
            result = asyncio.run(self.session._handle_dialog_silence_control("你好"))
        finally:
            get_dialog_silence_state_store().clear(
                "tenant-silence",
                "frontdesk-silence-followup",
            )

        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "dialog_silenced")
        transport.send_client_interrupt.assert_awaited_once()
        self.assertEqual(self.session._current_tts_type, "")
        self.assertEqual(self.session._current_audio_chunks, [])
        self.session._speak_scene_response.assert_not_awaited()

    def test_dialog_silence_feedback_uses_scene_reply_and_omni_tts(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        self.session.send_json = sender
        transport = SimpleNamespace(send_client_interrupt=AsyncMock())
        self.session.transport = transport
        self.session.tenant_id = "tenant-silence"
        self.session.device_id = "frontdesk-silence-scene"
        self.session.set_context(
            [
                {"role": "user", "content": "我刚才问你今天的安排"},
                {"role": "assistant", "content": "我说下午有访客预约。"},
            ]
        )
        self.session._person_memory_prompt = "可靠人物记忆：用户喜欢简短回答。"
        self.session._generate_scene_reply = AsyncMock(
            return_value="好，我先安静一会儿，喊小鹿我再回来。"
        )
        self.session._synthesize_sentence = AsyncMock(return_value=1.0)
        self.session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="小鹿",
                wake_aliases=("小鹿", "鹿鹿"),
            )
        )

        try:
            result = asyncio.run(
                self.session._handle_dialog_silence_control("别说话了")
            )
        finally:
            get_dialog_silence_state_store().clear(
                "tenant-silence",
                "frontdesk-silence-scene",
            )

        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "dialog_silenced")
        silence_event = next(item for item in sent if item.get("type") == "dialog_silence")
        self.assertTrue(silence_event["dynamicFeedback"])
        self.assertEqual(silence_event["responseText"], "")
        self.assertEqual(silence_event["backend"], "omni")
        transport.send_client_interrupt.assert_awaited_once()
        self.session._generate_scene_reply.assert_awaited_once()
        scene_kwargs = self.session._generate_scene_reply.await_args.kwargs
        self.assertEqual(scene_kwargs["scene"], "dialog_silence_mute")
        self.assertIn("已开启静音", scene_kwargs["required_facts"][0])
        self.assertIn("喊小鹿", scene_kwargs["required_facts"][0])
        self.session._synthesize_sentence.assert_awaited_once_with(
            "好，我先安静一会儿，喊小鹿我再回来。",
            1,
        )
        self.assertIn(
            {"type": "llm_delta", "text": "好，我先安静一会儿，喊小鹿我再回来。"},
            sent,
        )

    def test_dialog_silence_wake_feedback_uses_scene_reply_and_omni_tts(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        self.session.send_json = sender
        transport = SimpleNamespace(send_client_interrupt=AsyncMock())
        self.session.transport = transport
        self.session.tenant_id = "tenant-silence"
        self.session.device_id = "frontdesk-silence-wake-scene"
        self.session._dialog_silenced = True
        self.session._dialog_silence_status_text = "静音中，喊小鹿唤醒我"
        self.session._generate_scene_reply = AsyncMock(return_value="我回来啦，现在继续听你说。")
        self.session._synthesize_sentence = AsyncMock(return_value=1.0)
        self.session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="小鹿",
                wake_aliases=("小鹿", "鹿鹿"),
            )
        )

        try:
            result = asyncio.run(self.session._handle_dialog_silence_control("小鹿"))
        finally:
            get_dialog_silence_state_store().clear(
                "tenant-silence",
                "frontdesk-silence-wake-scene",
            )

        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "dialog_resumed")
        silence_event = next(item for item in sent if item.get("type") == "dialog_silence")
        self.assertTrue(silence_event["dynamicFeedback"])
        self.assertEqual(silence_event["responseText"], "")
        self.assertEqual(silence_event["backend"], "omni")
        transport.send_client_interrupt.assert_awaited_once()
        self.session._generate_scene_reply.assert_awaited_once()
        scene_kwargs = self.session._generate_scene_reply.await_args.kwargs
        self.assertEqual(scene_kwargs["scene"], "dialog_silence_wake")
        self.assertIn("已解除静音", scene_kwargs["required_facts"][0])
        self.session._synthesize_sentence.assert_awaited_once_with(
            "我回来啦，现在继续听你说。",
            1,
        )
        self.assertIn(
            {"type": "llm_delta", "text": "我回来啦，现在继续听你说。"},
            sent,
        )

    def test_client_stop_times_out_before_rag_budget_when_asr_never_ends(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session.transport = SimpleNamespace(
            send_audio=AsyncMock(),
            send_client_interrupt=AsyncMock(),
            close=AsyncMock(),
        )
        session._started = True
        session._turn_active = True
        session._last_user_text = "还没结束的半句"
        session._end_smooth_window_ms = Mock(return_value=20)

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS",
            0.03,
        ):
            asyncio.run(session.finish_audio())

        self.assertTrue(session.is_turn_finished)
        self.assertEqual(session._recycle_transport_reason, "asr_final_timeout")
        self.assertIsNone(session.transport)
        self.assertTrue(
            any(
                payload.get("type") == "error"
                and payload.get("code") == "asr_final_timeout"
                and payload.get("recoverable") is True
                for payload in sent
            )
        )
        self.assertTrue(
            any(
                payload.get("type") == "done"
                and payload.get("reason") == "asr_final_timeout"
                for payload in sent
            )
        )

    def test_empty_asr_stop_recovers_before_full_asr_timeout(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session.transport = SimpleNamespace(
            send_audio=AsyncMock(),
            send_client_interrupt=AsyncMock(),
            close=AsyncMock(),
        )
        session._started = True
        session._turn_active = True
        session._end_smooth_window_ms = Mock(return_value=0)

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS",
            1.0,
        ), patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS",
            0.03,
        ):
            asyncio.run(session.finish_audio())

        self.assertTrue(session.is_turn_finished)
        self.assertEqual(session._recycle_transport_reason, "empty_asr_final_timeout")
        self.assertIsNone(session.transport)
        self.assertFalse(
            any(payload.get("type") == "error" for payload in sent)
        )
        self.assertTrue(
            any(
                payload.get("type") == "done"
                and payload.get("reason") == "empty_asr"
                for payload in sent
            )
        )

    def test_client_stop_keeps_waiting_for_answer_after_asr_finalizes(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        session.transport = SimpleNamespace(send_audio=AsyncMock())
        session._started = True
        session._turn_active = True
        session._input_ended = True
        session._asr_ended.set()

        async def scenario() -> None:
            waiter = asyncio.create_task(session.finish_audio())
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            await session._complete_turn(reason="ok")
            await waiter

        asyncio.run(scenario())

        self.assertTrue(session.is_turn_finished)
        self.assertEqual(session._recycle_transport_reason, "")

    def test_asr_timeout_rebuilds_transport_before_next_turn(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        session._finished.set()
        session._turn_active = False
        session._recycle_transport_reason = "asr_final_timeout"
        session._connect_transport = AsyncMock()

        asyncio.run(session.prepare_next_turn())

        self.assertTrue(session._turn_active)
        self.assertFalse(session.is_turn_finished)
        self.assertEqual(session._recycle_transport_reason, "")
        session._connect_transport.assert_awaited_once()

    def test_persona_change_rebuilds_transport_before_next_turn(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        session._finished.set()
        session._turn_active = False
        session._started = True
        session._voice_settings = OmniSessionSettings(
            tenant_id="tenant-a",
            speaker_id="S_voice_a",
            fallback_speaker_id="zh_female_vv_jupiter_bigtts",
            model="1.2.1.1",
            realtime_resource_id="volc.speech.dialog",
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="expressive",
            speaking_style="租户音色风格",
            profile_version=7,
            clone_enabled=True,
        )
        session._persona_settings = SimpleNamespace(
            assistant_name="叮当",
            wake_aliases=("叮当",),
            version=8,
            customized=True,
            system_role="旧实时沟通人设。",
            speaking_style="旧说话风格。",
        )
        session._resolve_voice_settings = AsyncMock(
            return_value=session._voice_settings,
        )
        session._resolve_persona_settings = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="小丑",
                wake_aliases=("小丑", "丑丑"),
                version=9,
                customized=True,
                system_role="新实时沟通人设。不要自称叮当。",
                speaking_style="新说话风格。",
            )
        )
        session._recycle_transport = AsyncMock()
        session._connect_transport = AsyncMock()

        asyncio.run(session.prepare_next_turn())

        session._recycle_transport.assert_awaited_once_with("avatar_persona_changed")
        session._connect_transport.assert_awaited_once()
        self.assertTrue(session._turn_active)
        self.assertFalse(session.is_turn_finished)

    def test_asr_result_after_server_vad_cannot_replace_completed_query(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session._last_user_text = "第一轮问题"
        session._input_ended = True

        asyncio.run(
            session._handle_omni_response(
                {
                    "event": 451,
                    "payload_msg": {
                        "results": [
                            {"text": "第二轮迟到问题", "is_interim": False}
                        ]
                    },
                }
            )
        )

        self.assertEqual(session._last_user_text, "第一轮问题")
        self.assertEqual(session._late_asr_events, 1)
        self.assertEqual(sent, [])

    def test_start_payload_uses_o2_and_server_vad(self) -> None:
        self.session.set_context(
            [
                {"role": "assistant", "content": "orphan"},
                {"role": "user", "content": "上次的问题"},
                {"role": "assistant", "content": "上次的回答"},
                {"role": "user", "content": "incomplete"},
            ]
        )
        self.session.set_metadata(
            {
                "conversation_id": "conversation-1",
            }
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="张伟",
            verified=True,
        )
        self.session._person_memory_prompt = (
            "<person_memory>已确认的长期记忆：喜欢喝美式咖啡</person_memory>"
        )

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_DYNAMIC_NO_CACHE",
            False,
        ):
            payload = self.session._build_start_session_payload()

        self.assertEqual(payload["dialog"]["extra"]["model"], "1.2.1.1")
        self.assertTrue(payload["asr"]["extra"]["enable_custom_vad"])
        self.assertGreaterEqual(payload["asr"]["extra"]["end_smooth_window_ms"], 500)
        self.assertEqual(payload["tts"]["audio_config"]["format"], "pcm_s16le")
        self.assertEqual(payload["dialog"]["extra"]["input_mod"], "keep_alive")
        self.assertTrue(payload["dialog"]["extra"]["enable_conversation_truncate"])
        self.assertIn("张伟", payload["dialog"]["system_role"])
        self.assertIn("喜欢喝美式咖啡", payload["dialog"]["system_role"])
        self.assertIn("自然利用", payload["dialog"]["system_role"])
        self.assertEqual(
            payload["dialog"]["dialog_context"],
            [
                {"role": "user", "text": "上次的问题"},
                {"role": "assistant", "text": "上次的回答"},
            ],
        )

    def test_start_payload_uses_tenant_avatar_persona(self) -> None:
        self.session._persona_settings = SimpleNamespace(
            assistant_name="小丑",
            wake_aliases=("小丑", "丑丑"),
            version=9,
            customized=True,
            system_role="你是小丑。不要自称叮当。实时沟通必须带一点反差幽默。",
            speaking_style="短句，直接，有一点损但不冒犯。",
        )

        payload = self.session._build_start_session_payload()

        self.assertEqual(payload["dialog"]["bot_name"], "小丑")
        self.assertIn("不要自称叮当", payload["dialog"]["system_role"])
        self.assertIn("反差幽默", payload["dialog"]["system_role"])
        self.assertIn("有一点损", payload["dialog"]["speaking_style"])

    def test_clone_payload_includes_expressive_model(self) -> None:
        self.session._voice_settings = OmniSessionSettings(
            tenant_id="tenant-a",
            speaker_id="S_voice_a",
            fallback_speaker_id="zh_female_vv_jupiter_bigtts",
            model="1.2.1.1",
            realtime_resource_id="volc.speech.dialog",
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="expressive",
            speaking_style="语速自然，停顿轻松，偶尔使用嗯、呀等语气词。",
            profile_version=7,
            clone_enabled=True,
        )

        payload = self.session._build_start_session_payload()

        self.assertEqual(payload["tts"]["speaker"], "S_voice_a")
        self.assertEqual(
            payload["tts"]["extra"]["tts_2.0_model"],
            "expressive",
        )
        self.assertIn("停顿轻松", payload["dialog"]["speaking_style"])

    def test_default_voice_does_not_send_clone_extra(self) -> None:
        self.session._voice_settings = OmniSessionSettings(
            tenant_id="tenant-a",
            speaker_id="zh_female_vv_jupiter_bigtts",
            fallback_speaker_id="zh_female_vv_jupiter_bigtts",
            model="1.2.1.1",
            realtime_resource_id="volc.speech.dialog",
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="",
            speaking_style="",
            profile_version=7,
            clone_enabled=False,
        )

        self.assertNotIn("extra", self.session._build_start_session_payload()["tts"])

    def test_legacy_vortex_surface_metadata_uses_tenant_voice(self) -> None:
        self.session.set_metadata(
            {
                "tenant_id": "tenant-a",
                "device_id": "frontdesk-001",
                "frontdesk_surface": "vortex",
                "model_key": "natori",
            }
        )

        service = Mock()
        service.resolve.return_value = OmniSessionSettings(
            tenant_id="tenant-a",
            speaker_id="S_tenant_voice",
            fallback_speaker_id="zh_female_vv_jupiter_bigtts",
            model="1.2.1.1",
            realtime_resource_id="volc.speech.dialog",
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="expressive",
            speaking_style="租户配置语气",
            profile_version=12,
            clone_enabled=True,
        )

        with patch(
            "core.speech_streaming.omni.get_tenant_voice_profile_service",
            return_value=service,
        ):
            settings = asyncio.run(self.session._resolve_voice_settings())

        self.assertEqual(self.session.frontdesk_surface, "avatar")
        service.resolve.assert_called_once_with("tenant-a")
        self.assertEqual(settings.speaker_id, "S_tenant_voice")
        self.assertTrue(settings.clone_enabled)
        self.assertEqual(settings.profile_version, 12)

    def test_interrupt_truncates_played_context_and_never_completes_memory(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        transport = SimpleNamespace(
            send_conversation_truncate=AsyncMock(),
            close=AsyncMock(),
        )
        session.transport = transport
        session._started = True
        session._turn_active = True
        session._last_user_text = "被打断的问题"
        session._answer_parts = ["这段回答只播放了一部分"]

        asyncio.run(
            session.interrupt(
                played_reply_id="reply-1",
                played_ms=860,
            )
        )

        transport.send_conversation_truncate.assert_awaited_once_with("reply-1", 860)
        transport.close.assert_not_awaited()
        self.assertIsNone(session.take_completed_turn())
        self.assertTrue(session.is_turn_finished)
        self.assertEqual(len(session._context), 2)
        self.assertIn("被打断的问题", session._context[0]["content"])
        self.assertIn("被用户打断", session._context[1]["content"])
        self.assertTrue(
            any(
                payload.get("type") == "done"
                and payload.get("reason") == "interrupted"
                for payload in sent
            )
        )

    def test_completed_answer_is_committed_only_when_playback_is_acknowledged(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        session._last_user_text = "你还记得我吗"
        session._answer_parts = ["当然记得。"]

        asyncio.run(session._complete_turn())

        self.assertEqual(session._context, [])
        self.assertEqual(
            session.take_completed_turn(),
            ("你还记得我吗", "当然记得。"),
        )
        self.assertEqual(
            session._context,
            [
                {"role": "user", "content": "你还记得我吗"},
                {"role": "assistant", "content": "当然记得。"},
            ],
        )

    def test_interrupt_after_generation_done_keeps_short_context_only(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        transport = SimpleNamespace(
            send_conversation_truncate=AsyncMock(),
            close=AsyncMock(),
        )
        session.transport = transport
        session._started = True
        session._turn_active = True
        session._last_user_text = "给我讲长一点"
        session._answer_parts = ["这是已经生成、但还没有播放完的回答。"]

        async def scenario() -> None:
            await session._complete_turn()
            await session.interrupt(
                played_reply_id="reply-finished",
                played_ms=1250,
            )

        asyncio.run(scenario())

        transport.send_conversation_truncate.assert_awaited_once_with(
            "reply-finished", 1250
        )
        transport.close.assert_not_awaited()
        self.assertIsNone(session.take_completed_turn())
        self.assertEqual(len(session._context), 2)
        self.assertEqual(session._context[0]["role"], "user")
        self.assertEqual(session._context[0]["content"], "给我讲长一点")
        self.assertEqual(session._context[1]["role"], "assistant")
        self.assertIn("被用户打断", session._context[1]["content"])
        self.assertIn("这是已经生成", session._context[1]["content"])

    def test_interrupt_uses_browser_reported_context_for_next_turn(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        transport = SimpleNamespace(
            send_conversation_truncate=AsyncMock(),
            close=AsyncMock(),
        )
        session.transport = transport
        session._started = True
        session._turn_active = True
        session._last_user_text = "旧识别"
        session._answer_parts = ["内部回答"]

        asyncio.run(
            session.interrupt(
                played_reply_id="reply-ui",
                played_ms=420,
                previous_user_text="你刚才说的方案是什么",
                assistant_text="我刚才解释了第一种方案。",
                active_sentence="我刚才解释了第一种方案。",
                client_mode="barge_in",
            )
        )

        self.assertIsNone(session.take_completed_turn())
        self.assertEqual(session._context[0]["content"], "你刚才说的方案是什么")
        self.assertIn("我刚才解释了第一种方案", session._context[1]["content"])
        self.assertIn("420ms", session._context[1]["content"])

    def test_interrupt_recycles_upstream_before_next_barge_in_turn(self) -> None:
        session = OmniVoicePipelineSession(_discard)
        transport = SimpleNamespace(
            send_conversation_truncate=AsyncMock(),
            close=AsyncMock(),
        )
        session.transport = transport
        session._started = True
        session._voice_settings = OmniSessionSettings(
            tenant_id="tenant-a",
            speaker_id="zh_female_vv_jupiter_bigtts",
            fallback_speaker_id="zh_female_vv_jupiter_bigtts",
            model="1.2.1.1",
            realtime_resource_id="volc.speech.dialog",
            training_resource_id="seed-icl-2.0",
            tts_2_0_model="",
            speaking_style="",
            profile_version=7,
            clone_enabled=False,
        )
        session._turn_active = True
        session._recycle_transport = AsyncMock()
        session._connect_transport = AsyncMock()
        session._resolve_voice_settings = AsyncMock(
            return_value=session._voice_settings,
        )

        async def scenario() -> None:
            await session.interrupt(
                played_reply_id="reply-barge",
                played_ms=900,
            )
            await session.prepare_next_turn()

        asyncio.run(scenario())

        transport.send_conversation_truncate.assert_awaited_once_with(
            "reply-barge",
            900,
        )
        transport.close.assert_not_awaited()
        session._recycle_transport.assert_awaited_once_with("interrupted")
        session._connect_transport.assert_awaited_once()
        self.assertEqual(session._recycle_transport_reason, "")

    def test_unverified_client_name_is_not_injected_into_system_role(self) -> None:
        self.session.set_metadata(
            {
                "person_id": "spoofed-id",
                "person_name": "伪造姓名",
            }
        )

        payload = self.session._build_start_session_payload()

        self.assertFalse(self.session.person_identity_verified)
        self.assertNotIn("伪造姓名", payload["dialog"]["system_role"])

    def test_verified_person_identity_query_uses_external_rag(self) -> None:
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        transport = self._mock_person_context_external_success()
        self.session._handle_voice_action = AsyncMock(return_value=False)

        asyncio.run(self.session._route_completed_query("你知道我是谁吗？"))

        transport.send_external_rag.assert_awaited_once()
        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("person_identity", payload)
        self.assertIn("姓名：小游", payload)
        self.assertIn("不要每次固定", payload)
        self.assertIn("不要逐字复述本材料", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once()
        self.session._handle_voice_action.assert_not_awaited()

    def test_chat_intent_with_person_memory_bypasses_external_rag(self) -> None:
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._release_default_response = AsyncMock()
        self.session._person_memory_prompt = (
            "<person_memory>已确认的长期记忆：喜欢喝美式咖啡</person_memory>"
        )
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("chat must not build external RAG")
        )
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_CHAT,
            "obvious_chat",
        )

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(self.session._route_completed_query("不想了解。"))

        self.session._release_default_response.assert_awaited_once()
        self.session._build_external_rag.assert_not_called()

    def test_person_memory_snapshot_is_loaded_once_per_trusted_binding(self) -> None:
        service = Mock()
        service.build_session_context.return_value = (
            "<person_memory>已确认的长期记忆：喜欢喝美式咖啡</person_memory>"
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
            privacy_epoch=3,
        )

        async def scenario() -> None:
            await self.session.load_person_memory_context()
            await self.session.load_person_memory_context()

        with patch(
            "core.speech_streaming.pipeline.get_person_memory_service",
            return_value=service,
        ):
            asyncio.run(scenario())

        service.build_session_context.assert_called_once_with(
            person_id="employee-1",
            memory_read_allowed=True,
        )
        self.assertIn("美式咖啡", self.session._person_memory_prompt)

    def test_volume_action_stays_inside_current_voice_turn(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session.conversation_id = "conversation-volume"
        session.action_executor = Mock()
        session.action_executor.execute.return_value = DialogActionExecution(
            handled=True,
            status="executed",
            response="你看看这个音量怎么样。",
            action=ACTION_ADJUST_SYSTEM_VOLUME,
            task_id="task-volume",
            payload={
                "direction": "increase",
                "delta": 10,
                "response_style": "ask_check",
                "target": "system",
            },
        )
        session._wait_for_audible_action_effect = AsyncMock(return_value="")
        session._speak_scene_response = AsyncMock(
            side_effect=["音量我正在处理。", "这个音量你再感受一下。"]
        )

        proposal = DialogActionProposal(
            action=ACTION_ADJUST_SYSTEM_VOLUME,
            confidence=0.9,
            params={"direction": "increase"},
            source="agent_intent_router",
        )

        handled = asyncio.run(
            session._execute_voice_action(proposal, "帮我把音量调大一点")
        )

        self.assertTrue(handled)
        self.assertEqual(
            session.take_completed_turn(),
            ("帮我把音量调大一点", "这个音量你再感受一下。"),
        )
        self.assertNotIn(
            "volume_calibration_listening",
            [payload.get("type") for payload in sent],
        )
        self.assertEqual(session._speak_scene_response.await_count, 2)
        session._speak_scene_response.assert_any_await(
            "正在为你调节音量。",
            command=ACTION_ADJUST_SYSTEM_VOLUME,
            scene=f"{ACTION_ADJUST_SYSTEM_VOLUME}_progress",
            user_text="帮我把音量调大一点",
            required_facts=["正在为你调节音量。"],
            response_goal="先让用户知道正在执行音量调整。",
            constraints=["不要说调整已经最终完成。"],
        )
        session._speak_scene_response.assert_any_await(
            "你看看这个音量怎么样。",
            command=ACTION_ADJUST_SYSTEM_VOLUME,
            scene=ACTION_ADJUST_SYSTEM_VOLUME,
            user_text="帮我把音量调大一点",
            required_facts=["你看看这个音量怎么样。"],
            response_goal="自然告知语音动作的执行结果。",
            constraints=["不能改变动作是否成功、是否等待输入、是否超时或失败。"],
        )

    def test_verified_conversation_recall_uses_session_context(self) -> None:
        self.session.set_context(
            [
                {"role": "user", "content": "去哪里吃饭？"},
                {"role": "assistant", "content": "楼下的和平饭店。"},
                {"role": "user", "content": "你们公司做什么产品呢？"},
                {"role": "assistant", "content": "我们做企业级AI产品。"},
            ]
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("你记得我上次跟你说的啥吗？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("conversation recall must not use company RAG")
        )

        asyncio.run(
            self.session._route_completed_query("你记得我上次跟你说的啥吗？")
        )

        transport.send_external_rag.assert_awaited_once()
        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("conversation_recall", payload)
        self.assertIn("你们公司做什么产品呢", payload)
        self.assertIn("去哪里吃饭", payload)
        self.assertIn("不要直接照抄", payload)
        self.assertIn("不要逐字复述本材料", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once()
        self.session._handle_voice_action.assert_not_awaited()
        self.session._build_external_rag.assert_not_called()

    def test_yesterday_conversation_recall_uses_dated_person_memory(self) -> None:
        self.session.set_context(
            [
                {"role": "user", "content": "刚刚这一句不应该作为昨天"},
            ]
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        memory_service = Mock()
        memory_service.recall_daily_conversation.return_value = {
            "target_date": "2026-07-22",
            "target_label": "昨天",
            "turns": (
                {
                    "user_text": "你的名字是什么？",
                    "assistant_text": "我叫叮当。",
                },
                {
                    "user_text": "介绍一下产品。",
                    "assistant_text": "我们做数字人。",
                },
            ),
        }
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("那你现在记得昨天我们聊了什么吗？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("dated conversation recall must not use company RAG")
        )

        with patch(
            "core.speech_streaming.omni.get_person_memory_service",
            return_value=memory_service,
        ):
            asyncio.run(
                self.session._route_completed_query(
                    "那你现在记得昨天我们聊了什么吗？"
                )
            )

        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("昨天", payload)
        self.assertIn("你的名字是什么", payload)
        self.assertIn("介绍一下产品", payload)
        self.assertIn("不要逐字背诵", payload)
        self.assertNotIn("刚刚这一句", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        memory_service.recall_daily_conversation.assert_called_once()
        self.session._build_external_rag.assert_not_called()

    def test_asr_noisy_yesterday_recall_uses_dated_person_memory(self) -> None:
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        memory_service = Mock()
        memory_service.recall_daily_conversation.return_value = {
            "target_date": "2026-07-22",
            "target_label": "昨天",
            "summary": "聊了签退时间和对话回忆。",
            "turns": (),
            "source_turn_count": 3,
        }
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("继昨天我们说过啥吗？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("ASR noisy recall must not use company RAG")
        )

        with patch(
            "core.speech_streaming.omni.get_person_memory_service",
            return_value=memory_service,
        ):
            asyncio.run(self.session._route_completed_query("继昨天我们说过啥吗？"))

        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("昨天", payload)
        self.assertIn("签退时间", payload)
        self.assertIn("对话回忆", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        memory_service.recall_daily_conversation.assert_called_once()
        self.session._build_external_rag.assert_not_called()

    def test_ambiguous_conversation_recall_clarifies_without_memory_or_rag(self) -> None:
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        memory_service = Mock()
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("昨天我们聊了很多。")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("ambiguous recall must clarify before RAG")
        )

        with patch(
            "core.speech_streaming.omni.get_person_memory_service",
            return_value=memory_service,
        ):
            asyncio.run(self.session._route_completed_query("昨天我们聊了很多。"))

        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("你是想让我回忆昨天我们聊过什么吗", payload)
        self.assertIn("澄清问题", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        memory_service.recall_daily_conversation.assert_not_called()
        self.session._build_external_rag.assert_not_called()

    def test_anonymous_yesterday_recall_uses_identity_gate(self) -> None:
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("昨天聊了啥？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("anonymous recall must not use RAG")
        )

        asyncio.run(self.session._route_completed_query("昨天聊了啥？"))

        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("身份尚未通过服务端可信识别确认", payload)
        self.assertIn("不能读取个人对话记录", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        self.session._build_external_rag.assert_not_called()

    def test_person_context_external_rag_waits_for_default_without_interrupt(self) -> None:
        transport = self._mock_person_context_external_success()
        transport.send_client_interrupt = AsyncMock()
        self.session._response_types_seen.add(TTS_TYPE_DEFAULT)
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("我是谁？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)

        asyncio.run(self.session._route_completed_query("我是谁？"))

        self.session._wait_for_default_tts_end_for_external_rag.assert_awaited_once()
        transport.send_external_rag.assert_awaited_once()
        transport.send_client_interrupt.assert_not_awaited()

    def test_person_context_external_rag_error_speaks_failure_notice(self) -> None:
        transport = SimpleNamespace(
            send_external_rag=AsyncMock(),
            send_client_interrupt=AsyncMock(),
        )
        self.session.transport = transport
        self.session.set_context(
            [
                {"role": "user", "content": "今天学习什么？"},
                {"role": "assistant", "content": "我们今天学习并发控制。"},
            ]
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        self.session._generate_scene_reply = AsyncMock(
            side_effect=AssertionError("Omni person context must not use DashScope")
        )
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )
        self.session._request_external_rag_response = AsyncMock(
            side_effect=RuntimeError("Volc external RAG timeout")
        )
        self.session._release_default_response = AsyncMock(return_value=False)
        self.session._send = AsyncMock(return_value=True)
        self.session._synthesize_sentence = AsyncMock(return_value=0.5)
        self.session._complete_turn = AsyncMock()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("我们之前聊过什么？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("person recall must not use company RAG")
        )

        asyncio.run(self.session._route_completed_query("我们之前聊过什么？"))

        transport.send_external_rag.assert_not_awaited()
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._release_default_response.assert_awaited_once_with(
            reason="conversation_recall_external_error"
        )
        reply = self.session._synthesize_sentence.await_args.args[0]
        self.assertIn("没法整理之前的对话", reply)
        self.assertNotIn("记得", reply)
        self.session._complete_turn.assert_awaited_once_with(
            reason="conversation_recall_external_error"
        )
        self.session._build_external_rag.assert_not_called()

    def test_verified_assistant_recall_uses_latest_assistant_context(self) -> None:
        self.session.set_context(
            [
                {"role": "user", "content": "今天学习什么？"},
                {"role": "assistant", "content": "我们今天学习并发控制。"},
            ]
        )
        self.session.set_person_context(
            person_id="employee-1",
            person_name="小游",
            verified=True,
        )
        transport = self._mock_person_context_external_success()
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("你刚才说了什么？")
        )
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._build_external_rag = Mock(
            side_effect=AssertionError("assistant recall must not use RAG")
        )

        asyncio.run(self.session._route_completed_query("你刚才说了什么？"))

        payload = transport.send_external_rag.await_args.args[0]
        self.assertIn("我回答过的内容主题：我们今天学习并发控制", payload)
        self.assertNotIn("用户: 今天学习什么", payload)
        self.session._generate_scene_reply.assert_not_awaited()
        self.session._synthesize_sentence.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once()
        self.session._handle_voice_action.assert_not_awaited()
        self.session._build_external_rag.assert_not_called()

    def test_external_rag_builder_reuses_intent_probe_results(self) -> None:
        result = SimpleNamespace(
            title="产品说明",
            source_path="product.md",
            content="公司提供数字人产品。",
        )

        with patch(
            "core.speech_streaming.omni.get_knowledge_service",
            side_effect=AssertionError("precomputed results must be reused"),
        ):
            payload = self.session._build_external_rag("公司产品", [result])

        self.assertIn("产品说明", payload)
        self.assertIn("数字人产品", payload)

    def test_external_rag_route_sends_502_after_default_settles(self) -> None:
        events: list[str] = []
        transport = SimpleNamespace(
            send_chat_tts_text=AsyncMock(
                side_effect=lambda text: events.append(f"500:{text}")
            ),
            send_client_interrupt=AsyncMock(
                side_effect=lambda: events.append("515")
            ),
            send_external_rag=AsyncMock(
                side_effect=lambda _payload: events.append("502")
            )
        )
        self.session.transport = transport
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(
            return_value='[{"title":"资料"}]'
        )
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 1.0

        async def external_response(sender) -> float:
            await sender()
            self.session._commit_external_response()
            return 1.0

        self.session._request_tts_response = AsyncMock(
            side_effect=tts_response
        )
        self.session._request_external_rag_response = AsyncMock(
            side_effect=external_response
        )
        self.session._complete_turn = AsyncMock()

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(
                self.session._route_completed_query("公司名字是什么？")
            )

        self.assertEqual(events, ["502"])
        self.session._wait_for_default_tts_end_for_external_rag.assert_awaited_once_with(
            payload_chars=len('[{"title":"资料"}]')
        )
        transport.send_client_interrupt.assert_not_awaited()
        transport.send_external_rag.assert_awaited_once_with('[{"title":"资料"}]')
        self.session._request_tts_response.assert_not_awaited()
        self.session._request_external_rag_response.assert_awaited_once()
        self.assertEqual(self.session._answer_parts, [])
        self.session._complete_turn.assert_awaited_once()

    def test_external_rag_502_is_not_prefilled_by_server_answer(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        transport = SimpleNamespace(
            send_chat_tts_text=AsyncMock(),
            send_client_interrupt=AsyncMock(),
            send_external_rag=AsyncMock(),
        )
        session.transport = transport
        session._resolve_avatar_persona = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="叮当",
                wake_aliases=("叮当", "小叮当"),
            )
        )
        session._resolve_persona_settings = AsyncMock(
            return_value=SimpleNamespace(
                assistant_name="叮当",
                wake_aliases=("叮当", "小叮当"),
                version=0,
                system_role="你是前台数字人。",
                speaking_style="自然简短。",
            )
        )
        session._handle_voice_action = AsyncMock(return_value=False)
        session.rag_intent_router = Mock()
        session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        session._build_external_rag = Mock(return_value='[{"title":"资料"}]')
        session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 1.0

        async def external_response(sender) -> float:
            await sender()
            session._commit_external_response()
            return 1.0

        session._request_tts_response = AsyncMock(side_effect=tts_response)
        session._request_external_rag_response = AsyncMock(
            side_effect=external_response
        )
        session._release_default_response = AsyncMock()
        session._complete_turn = AsyncMock()

        with patch("core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED", True):
            asyncio.run(session._route_completed_query("公司资料是什么？"))

        transport.send_chat_tts_text.assert_not_awaited()
        transport.send_external_rag.assert_awaited_once_with('[{"title":"资料"}]')
        transport.send_client_interrupt.assert_not_awaited()
        session._wait_for_default_tts_end_for_external_rag.assert_awaited_once()
        self.assertEqual(session._answer_parts, [])
        self.assertEqual(session._final_answer_text(), "")
        self.assertFalse(
            any(
                item.get("type") == "llm_delta"
                for item in sent
            )
        )

    def test_external_rag_commit_discards_buffered_default(self) -> None:
        events: list[str] = []
        transport = SimpleNamespace(
            send_chat_tts_text=AsyncMock(
                side_effect=lambda text: events.append(f"500:{text}")
            ),
            send_client_interrupt=AsyncMock(
                side_effect=lambda: events.append("515")
            ),
            send_external_rag=AsyncMock(
                side_effect=lambda _payload: events.append("502")
            )
        )
        self.session.transport = transport
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(
            return_value='[{"title":"资料"}]'
        )
        self.session._pending_default_sentences = [
            ("这是应该被清掉的普通回答。", [b"default-audio"], "default-reply"),
        ]
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 1.0

        async def external_response(sender) -> float:
            await sender()
            self.session._commit_external_response()
            return 1.0

        self.session._request_tts_response = AsyncMock(
            side_effect=tts_response
        )
        self.session._request_external_rag_response = AsyncMock(
            side_effect=external_response
        )
        self.session._complete_turn = AsyncMock()

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(
                self.session._route_completed_query("公司名字是什么？")
            )

        self.assertEqual(events, ["502"])
        transport.send_client_interrupt.assert_not_awaited()
        transport.send_external_rag.assert_awaited_once_with('[{"title":"资料"}]')
        self.session._wait_for_default_tts_end_for_external_rag.assert_awaited_once()
        self.assertEqual(self.session._pending_default_sentences, [])
        self.session._complete_turn.assert_awaited_once()

    def test_external_rag_timeout_before_commit_releases_buffered_default(
        self,
    ) -> None:
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("公司资料是什么？")
        )
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(return_value='[{"title":"资料"}]')
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )
        self.session.transport = SimpleNamespace(
            send_client_interrupt=AsyncMock(),
            send_external_rag=AsyncMock(),
            send_chat_tts_text=AsyncMock(),
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 0.2

        async def first_audio_timeout(sender) -> float:
            await sender()
            raise ExternalRagTimeout("first_audio", 0.1)

        self.session._request_tts_response = AsyncMock(side_effect=tts_response)
        self.session._request_external_rag_response = AsyncMock(
            side_effect=first_audio_timeout
        )
        self.session._expire_external_generation = AsyncMock()
        self.session._dispatch_sentence = AsyncMock()
        self.session._complete_turn = AsyncMock()
        self.session._pending_default_sentences = [
            ("这是命中前的旧普通回答。", [b"old-default-audio"], "old-default-reply"),
        ]
        self.session._default_response_ended = True

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(self.session._route_completed_query("公司资料是什么？"))

        self.session._dispatch_sentence.assert_awaited_once_with(
            "这是命中前的旧普通回答。",
            [b"old-default-audio"],
            TTS_TYPE_DEFAULT,
            "old-default-reply",
        )
        self.session._wait_for_default_tts_end_for_external_rag.assert_awaited_once()
        self.assertEqual(self.session._response_mode, "default")
        self.assertEqual(self.session._arbitration_state, "default")
        self.session._expire_external_generation.assert_awaited_once_with(
            "rag_first_audio_timeout"
        )
        self.session.transport.send_client_interrupt.assert_not_awaited()
        self.session.transport.send_external_rag.assert_awaited_once_with(
            '[{"title":"资料"}]'
        )
        self.session.transport.send_chat_tts_text.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once()

    def test_external_rag_timeout_before_commit_completes_without_default_text(
        self,
    ) -> None:
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session._handle_assistant_wake_name = AsyncMock(
            return_value=_wake_name_miss("公司资料是什么？")
        )
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(return_value='[{"title":"资料"}]')
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )
        self.session.transport = SimpleNamespace(
            send_client_interrupt=AsyncMock(),
            send_external_rag=AsyncMock(),
            send_chat_tts_text=AsyncMock(),
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 0.2

        async def first_audio_timeout(sender) -> float:
            await sender()
            raise ExternalRagTimeout("first_audio", 0.1)

        self.session._request_tts_response = AsyncMock(side_effect=tts_response)
        self.session._request_external_rag_response = AsyncMock(
            side_effect=first_audio_timeout
        )
        self.session._expire_external_generation = AsyncMock()
        self.session._dispatch_sentence = AsyncMock()
        self.session._complete_turn = AsyncMock()
        self.session._pending_default_sentences = []
        self.session._default_response_ended = False

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(self.session._route_completed_query("公司资料是什么？"))

        self.session._dispatch_sentence.assert_not_awaited()
        self.session._expire_external_generation.assert_awaited_once_with(
            "rag_first_audio_timeout"
        )
        self.session.transport.send_client_interrupt.assert_not_awaited()
        self.session.transport.send_external_rag.assert_awaited_once_with(
            '[{"title":"资料"}]'
        )
        self.session.transport.send_chat_tts_text.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once_with(
            reason="rag_first_audio_timeout"
        )

    def test_external_rag_completed_without_audio_releases_buffered_default(self) -> None:
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(return_value='[{"title":"资料"}]')
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )
        self.session.transport = SimpleNamespace(
            send_client_interrupt=AsyncMock(),
            send_external_rag=AsyncMock(),
            send_chat_tts_text=AsyncMock(),
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 0.2

        async def completed_without_audio(sender) -> float:
            await sender()
            return 0.0

        self.session._request_tts_response = AsyncMock(
            side_effect=tts_response
        )
        self.session._request_external_rag_response = AsyncMock(
            side_effect=completed_without_audio
        )
        self.session._expire_external_generation = AsyncMock()
        self.session._dispatch_sentence = AsyncMock()
        self.session._complete_turn = AsyncMock()
        self.session._pending_default_sentences = [
            (
                "这是命中前的旧普通回答。",
                [b"old-default-audio"],
                "old-default-reply",
            ),
        ]
        self.session._default_response_ended = True

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(self.session._route_completed_query("公司资料是什么？"))

        self.session._dispatch_sentence.assert_awaited_once_with(
            "这是命中前的旧普通回答。",
            [b"old-default-audio"],
            TTS_TYPE_DEFAULT,
            "old-default-reply",
        )
        self.session._wait_for_default_tts_end_for_external_rag.assert_awaited_once()
        self.session.transport.send_chat_tts_text.assert_not_awaited()
        self.session.transport.send_external_rag.assert_awaited_once_with(
            '[{"title":"资料"}]'
        )
        self.assertEqual(self.session._answer_parts, [])
        self.assertEqual(self.session._arbitration_state, "default")
        self.session._expire_external_generation.assert_awaited_once_with(
            "rag_no_external_audio"
        )
        self.session._complete_turn.assert_awaited_once()

    def test_external_rag_waits_for_completion_after_first_audio(self) -> None:
        self.session._response_mode = TTS_TYPE_EXTERNAL_RAG
        self.session._arbitration_state = "external_pending"
        self.session._dispatch_sentence = AsyncMock()

        async def scenario() -> float:
            task = asyncio.create_task(
                self.session._request_external_rag_response(AsyncMock())
            )
            await asyncio.sleep(0)
            self.session._current_tts_type = TTS_TYPE_EXTERNAL_RAG
            self.session._current_tts_text = "知识库首段回答。"
            self.session._current_reply_id = "rag-reply"
            self.session._current_audio_chunks = [b"rag-audio"]
            self.session._response_types_seen.add(TTS_TYPE_EXTERNAL_RAG)
            self.session._tts_expectation.record_audio(
                TTS_TYPE_EXTERNAL_RAG,
                len(b"rag-audio"),
            )
            await self.session._finish_current_sentence()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            await self.session._on_tts_ended({})
            return await task

        duration = asyncio.run(scenario())

        self.assertGreater(duration, 0.0)
        self.assertEqual(self.session._arbitration_state, "external_committed")

    def test_external_rag_completion_timeout_keeps_committed_answer(self) -> None:
        self.session._handle_voice_action = AsyncMock(return_value=False)
        self.session.rag_intent_router = Mock()
        self.session.rag_intent_router.route.return_value = DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            "knowledge_probe_hit",
            results=[SimpleNamespace(score=0.8)],
        )
        self.session._build_external_rag = Mock(return_value='[{"title":"资料"}]')
        self.session._wait_for_default_tts_end_for_external_rag = AsyncMock(
            return_value=0.0
        )
        self.session.transport = SimpleNamespace(
            send_client_interrupt=AsyncMock(),
            send_external_rag=AsyncMock(),
            send_chat_tts_text=AsyncMock(),
        )

        async def tts_response(_expected_type, sender, **_kwargs) -> float:
            await sender()
            return 0.2

        async def completion_timeout(sender) -> float:
            await sender()
            self.session._arbitration_state = "external_committed"
            self.session._answer_parts.append("这是已经提交的知识库回答。")
            raise ExternalRagTimeout("completion", 0.2)

        self.session._request_tts_response = AsyncMock(side_effect=tts_response)
        self.session._request_external_rag_response = AsyncMock(
            side_effect=completion_timeout
        )
        self.session._expire_external_generation = AsyncMock()
        self.session._release_default_response = AsyncMock()
        self.session._complete_turn = AsyncMock()

        with patch(
            "core.speech_streaming.omni.REALTIME_DIALOG_RAG_ENABLED",
            True,
        ):
            asyncio.run(self.session._route_completed_query("公司资料是什么？"))

        self.session._expire_external_generation.assert_awaited_once_with(
            "rag_completion_timeout"
        )
        self.session._release_default_response.assert_not_awaited()
        self.session._complete_turn.assert_awaited_once_with(
            reason="rag_completion_timeout"
        )
        self.session.transport.send_chat_tts_text.assert_not_awaited()
        self.session.transport.send_external_rag.assert_awaited_once_with(
            '[{"title":"资料"}]'
        )

    def test_failed_external_generation_recycles_transport_before_next_turn(self) -> None:
        self.session._finished.set()
        self.session._recycle_transport_reason = "rag_first_audio_timeout"
        self.session._recycle_transport = AsyncMock()
        self.session._connect_transport = AsyncMock()

        asyncio.run(self.session.prepare_next_turn())

        self.session._recycle_transport.assert_awaited_once_with(
            "rag_first_audio_timeout"
        )
        self.session._connect_transport.assert_awaited_once()
        self.assertEqual(self.session._recycle_transport_reason, "")

    def test_first_external_rag_audio_commits_and_discards_default(self) -> None:
        self.session._response_mode = TTS_TYPE_EXTERNAL_RAG
        self.session._arbitration_state = "external_pending"
        self.session._pending_default_sentences = [
            ("备用回答。", [b"default-audio"], "default-reply"),
        ]
        self.session._current_tts_type = TTS_TYPE_EXTERNAL_RAG
        self.session._current_tts_text = "知识库回答。"
        self.session._current_reply_id = "rag-reply"
        self.session._current_audio_chunks = [b"rag-audio"]
        self.session._dispatch_sentence = AsyncMock()

        asyncio.run(self.session._finish_current_sentence())

        self.assertEqual(self.session._arbitration_state, "external_committed")
        self.assertEqual(self.session._pending_default_sentences, [])
        self.session._dispatch_sentence.assert_awaited_once_with(
            "知识库回答。",
            [b"rag-audio"],
            TTS_TYPE_EXTERNAL_RAG,
            "rag-reply",
        )

    def test_external_rag_uses_nested_answer_text_for_status(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session._response_mode = TTS_TYPE_EXTERNAL_RAG
        session._arbitration_state = "external_pending"

        async def scenario() -> None:
            await session._handle_omni_response(
                {
                    "event": 350,
                    "payload_msg": {
                        "data": {
                            "tts_type": TTS_TYPE_EXTERNAL_RAG,
                            "reply_id": "rag-reply",
                            "output_text": "这是知识库回答。",
                        }
                    },
                }
            )
            await session._handle_omni_response(
                {
                    "message_type": "SERVER_ACK",
                    "payload_msg": b"\x00" * 640,
                }
            )
            await session._handle_omni_response({"event": 351, "payload_msg": {}})

        asyncio.run(scenario())

        audio_message = next(item for item in sent if item.get("type") == "tts_audio")
        delta_message = next(item for item in sent if item.get("type") == "llm_delta")
        self.assertEqual(audio_message["text"], "这是知识库回答。")
        self.assertEqual(delta_message["text"], "这是知识库回答。")

    def test_external_rag_error_after_commit_does_not_play_default(self) -> None:
        self.session._response_mode = TTS_TYPE_EXTERNAL_RAG
        self.session._arbitration_state = "external_committed"
        self.session._pending_default_sentences = [
            ("不能重复播放。", [b"default-audio"], "default-reply"),
        ]
        self.session._dispatch_sentence = AsyncMock()

        released = asyncio.run(
            self.session._release_default_response(reason="rag_tts_timeout")
        )

        self.assertFalse(released)
        self.session._dispatch_sentence.assert_not_awaited()

    def test_default_fallback_is_released_only_once(self) -> None:
        self.session._arbitration_state = "external_pending"
        self.session._pending_default_sentences = [
            ("只播放一次。", [b"default-audio"], "default-reply"),
        ]
        self.session._dispatch_sentence = AsyncMock()

        first = asyncio.run(
            self.session._release_default_response(reason="rag_tts_timeout")
        )
        second = asyncio.run(
            self.session._release_default_response(reason="duplicate")
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.session._dispatch_sentence.assert_awaited_once()

    def test_default_fallback_without_pending_text_returns_unreleased(self) -> None:
        self.session._arbitration_state = "external_pending"
        self.session._pending_default_sentences = []
        self.session._default_response_ended = False
        self.session._dispatch_sentence = AsyncMock()

        released = asyncio.run(
            self.session._release_default_response(reason="rag_first_audio_timeout")
        )

        self.assertFalse(released)
        self.session._dispatch_sentence.assert_not_awaited()

    def test_default_fallback_completes_with_nonempty_answer(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session._llm_started = True
        session._last_user_text = "你说了什么？"
        session._default_response_ended = True
        session._pending_default_sentences = [
            ("这是模型的普通回答。", [b"\x00" * 480], "default-reply"),
        ]

        asyncio.run(
            session._release_default_response(reason="rag_tts_timeout")
        )

        llm_end = next(item for item in sent if item.get("type") == "llm_end")
        self.assertEqual(llm_end["text"], "这是模型的普通回答。")
        self.assertTrue(session.is_turn_finished)

    def test_chat_tts_ignores_stale_pending_default_text(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)
        session._response_mode = TTS_TYPE_CHAT_TEXT
        session._pending_response_text = "啥？我爱喝咖啡，这是上游默认回答残留。"

        async def scenario() -> None:
            session._tts_expectation.begin(
                TTS_TYPE_CHAT_TEXT,
                expected_text="当然认识，你是小游。",
            )
            await session._handle_omni_response(
                {
                    "event": 350,
                    "payload_msg": {
                        "tts_type": TTS_TYPE_CHAT_TEXT,
                        "reply_id": "reply-identity",
                    },
                }
            )
            await session._handle_omni_response(
                {
                    "message_type": "SERVER_ACK",
                    "payload_msg": b"\x00" * 640,
                }
            )
            await session._handle_omni_response(
                {"event": 351, "payload_msg": {}}
            )
            session._tts_expectation.reset()

        asyncio.run(scenario())

        tts_audio = next(item for item in sent if item.get("type") == "tts_audio")
        self.assertEqual(tts_audio["text"], "当然认识，你是小游。")
        self.assertEqual(session._pending_response_text, "")

    def test_extract_asr_result_uses_latest_nonempty_result(self) -> None:
        text, interim = self.session._extract_asr_result(
            {
                "results": [
                    {"text": "你好", "is_interim": True},
                    {"text": "你好，请问会议室在哪", "is_interim": False},
                ]
            }
        )

        self.assertEqual(text, "你好，请问会议室在哪")
        self.assertFalse(interim)

    def test_dialog_context_only_contains_complete_pairs(self) -> None:
        self.session.set_context(
            [
                {"role": "user", "content": "问题一"},
                {"role": "assistant", "content": "回答一"},
                {"role": "user", "content": "问题二"},
            ]
        )

        self.assertEqual(
            self.session._build_dialog_context(),
            [
                {"role": "user", "text": "问题一"},
                {"role": "assistant", "text": "回答一"},
            ],
        )

    def test_person_recall_context_is_wider_than_model_context(self) -> None:
        history: list[dict] = []
        for index in range(1, 11):
            history.extend(
                [
                    {"role": "user", "content": f"历史问题{index}"},
                    {"role": "assistant", "content": f"历史回答{index}"},
                ]
            )

        self.session.set_context(history)
        self.session.set_person_memory_context(history)

        self.assertEqual(len(self.session._context), 6)
        self.assertEqual(len(self.session._person_memory_context), 20)
        self.assertEqual(
            self.session._context[0]["content"],
            "历史问题8",
        )
        self.assertEqual(
            self.session._person_memory_context[0]["content"],
            "历史问题1",
        )

    def test_stream_text_merge_accepts_full_updates_and_deltas(self) -> None:
        self.assertEqual(
            self.session._merge_stream_text("公司", "公司主要提供服务"),
            "公司主要提供服务",
        )
        self.assertEqual(
            self.session._merge_stream_text("公司主要", "提供服务"),
            "公司主要提供服务",
        )

    def test_audio_idle_timeout_is_treated_as_empty_input(self) -> None:
        self.assertTrue(
            self.session._is_idle_timeout(
                RuntimeError("codes=52000042, desc=DialogAudioIdleTimeoutError")
            )
        )
        self.assertFalse(self.session._is_idle_timeout(RuntimeError("other failure")))

    def test_reply_text_stream_only_emits_increment(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        session = OmniVoicePipelineSession(sender)

        async def scenario() -> None:
            session._allow_reply("reply-1")
            await session._emit_reply_text("reply-1", "公司主要")
            await session._emit_reply_text("reply-1", "公司主要提供AI服务")
            await session._emit_reply_text("reply-1", "公司主要提供AI服务")

        asyncio.run(scenario())
        self.assertEqual(
            [item["text"] for item in sent if item.get("type") == "llm_delta"],
            ["公司主要", "提供AI服务"],
        )
        self.assertEqual(session._final_answer_text(), "公司主要提供AI服务")

    def test_next_turn_resets_turn_state_but_keeps_context(self) -> None:
        self.session.set_context(
            [
                {"role": "user", "content": "上一问"},
                {"role": "assistant", "content": "上一答"},
            ]
        )
        self.session._finished.set()
        self.session._last_user_text = "旧问题"
        self.session._answer_parts = ["旧回答"]
        self.session._arbitration_state = "external_committed"
        self.session._default_fallback_released = True

        asyncio.run(self.session.prepare_next_turn())

        self.assertTrue(self.session.supports_multiple_turns)
        self.assertFalse(self.session._finished.is_set())
        self.assertEqual(self.session._last_user_text, "")
        self.assertEqual(self.session._arbitration_state, "routing")
        self.assertFalse(self.session._default_fallback_released)
        self.assertEqual(
            self.session._build_dialog_context(),
            [
                {"role": "user", "text": "上一问"},
                {"role": "assistant", "text": "上一答"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
