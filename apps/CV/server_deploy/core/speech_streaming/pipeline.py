"""Browser-facing ASR -> LLM stream -> TTS streaming pipeline."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import time
import uuid
import wave
from dataclasses import dataclass
from typing import Awaitable, Callable

from config import (
    VOICE_ASSISTANT_WAKE_REPLY,
    VOICE_PIPELINE_MAX_LLM_CHARS,
    VOICE_PIPELINE_SENTENCE_CHARS,
    VOICE_SYSTEM_VOLUME_TASK_WAIT_SECONDS,
)
from core.client_tasks import get_client_task_queue
from core.dialog_actions import (
    ACTION_ADJUST_SYSTEM_VOLUME,
    ACTION_ADJUST_VOLUME,
    DialogActionExecution,
    DialogActionExecutor,
    DialogActionProposal,
    DialogAgentIntentRouter,
)
from core.dialog_commands import DialogCommandRouter
from core.dialog_chat import get_dialog_chat_service
from core.dialog_silence import (
    ACTION_MUTE,
    ACTION_NONE,
    ACTION_SUPPRESS,
    ACTION_WAKE,
    DialogSilenceResult,
    get_dialog_silence_state_store,
    resolve_dialog_silence,
)
from core.dialog_wake_name import WakeNameResult, parse_wake_name
from core.person_memory import get_person_memory_service
from core.person_memory.commands import route_person_memory_command
from core.person_identity import get_person_identity_repository
from core.person_sessions.context_intent import PersonContextIntentRouter
from core.speech_streaming.volc_asr import VolcStreamingAsrClient
from core.speech_streaming.volc_tts import VolcStreamingTtsClient
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id
from core.tenant_avatar import get_tenant_avatar_persona_service

logger = logging.getLogger(__name__)

Sender = Callable[[dict], Awaitable[None]]


class VoicePipelineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DialogSilenceHandling:
    handled: bool
    route_text: str
    reason: str = "ok"
    status_text: str = ""
    resumed: bool = False


class VoicePipelineSession:
    def __init__(self, send_json: Sender):
        self.send_json = send_json
        self.asr = VolcStreamingAsrClient()
        self.tts = VolcStreamingTtsClient()
        self.command_router = DialogCommandRouter()
        self.agent_intent_router = DialogAgentIntentRouter()
        self.action_executor = DialogActionExecutor()
        self.person_context_intent_router = PersonContextIntentRouter()
        self.conversation_id = uuid.uuid4().hex
        self.device_id = ""
        self.tenant_id = DEFAULT_TENANT_ID
        self.frontdesk_surface = "avatar"
        self.model_key = ""
        self.person_id = ""
        self.person_name = ""
        self.person_identity_verified = False
        self.person_memory_read_allowed = False
        self.person_privacy_epoch = 0
        self._asr_events: asyncio.Queue[dict] = asyncio.Queue()
        self._asr_task: asyncio.Task | None = None
        self._context: list[dict] = []
        self._person_memory_context: list[dict] = []
        self._person_memory_prompt = ""
        self._person_memory_loaded_for: tuple[str, int] | None = None
        self._person_memory_load_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._closed = False
        self._terminal_sent = False
        self._last_completed_turn: tuple[str, str] | None = None
        self._dialog_silenced = False
        self._dialog_silence_status_text = ""

    @property
    def supports_multiple_turns(self) -> bool:
        return False

    @property
    def is_turn_finished(self) -> bool:
        return self._terminal_sent

    async def prepare_next_turn(self) -> None:
        raise VoicePipelineError("voice backend does not support multiple turns")

    async def interrupt(
        self,
        *,
        reason: str = "interrupted",
        played_reply_id: str = "",
        played_ms: int = 0,
        previous_user_text: str = "",
        assistant_text: str = "",
        active_sentence: str = "",
        client_mode: str = "",
    ) -> None:
        """Stop an unfinished turn without exposing it as completed memory."""

        del played_reply_id
        del played_ms
        del previous_user_text
        del assistant_text
        del active_sentence
        del client_mode
        self._last_completed_turn = None
        await self._send_done(reason)
        await self.close()
        logger.info(
            "语音轮次被打断: conversation=%s tenant=%s reason=%s",
            self.conversation_id,
            self.tenant_id,
            reason,
        )

    def take_completed_turn(self) -> tuple[str, str] | None:
        turn = self._last_completed_turn
        self._last_completed_turn = None
        return turn

    async def start(self) -> None:
        await self.asr.connect()
        self._asr_task = asyncio.create_task(self.asr.receive_loop(self._asr_events))
        await self._send({"type": "ready"})

    async def send_audio(self, audio: bytes) -> None:
        if not audio:
            return
        await self.asr.send_audio(audio, is_last=False)
        await self._drain_asr_events(block=False)

    def set_context(self, context: list[dict] | None) -> None:
        self._context = self._normalize_context(context, limit=6)
        if not self._person_memory_context:
            self._person_memory_context = list(self._context)

    def set_person_memory_context(self, context: list[dict] | None) -> None:
        """Keep a wider private history for deterministic person recall."""

        self._person_memory_context = self._normalize_context(context, limit=20)

    @staticmethod
    def _normalize_context(
        context: list[dict] | None,
        *,
        limit: int,
    ) -> list[dict]:
        normalized: list[dict] = []
        for item in context or []:
            role = str(item.get("role") or "")[:20]
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                normalized.append({"role": role, "content": content[:500]})
        return normalized[-max(1, limit) :]

    def set_metadata(self, metadata: dict | None) -> None:
        metadata = metadata or {}
        device_id = str(metadata.get("device_id") or metadata.get("deviceId") or "").strip()
        tenant_id = str(
            metadata.get("tenant_id") or metadata.get("tenantId") or self.tenant_id
        ).strip()
        conversation_id = str(
            metadata.get("conversation_id") or metadata.get("conversationId") or ""
        ).strip()
        person_id = str(metadata.get("person_id") or metadata.get("personId") or "").strip()
        person_name = str(metadata.get("person_name") or metadata.get("personName") or "").strip()
        model_key = str(
            metadata.get("model_key")
            or metadata.get("modelKey")
            or metadata.get("model")
            or self.model_key
        ).strip()
        if device_id:
            self.device_id = device_id[:80]
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.frontdesk_surface = "avatar"
        if model_key:
            self.model_key = re.sub(r"[^0-9A-Za-z_-]", "", model_key)[:40]
        if conversation_id:
            self.conversation_id = conversation_id[:120]
        # Person identity arriving in ordinary websocket metadata is only a hint.
        # A verified identity is set separately from the server-owned person
        # session snapshot and cannot be overwritten by later client messages.
        if not self.person_identity_verified:
            if person_id:
                self.person_id = person_id[:120]
            if person_name:
                self.person_name = person_name[:80]
        logger.info(
            "语音流元数据已更新: tenant=%s conversation=%s device=%s surface=%s model=%s person=%s person_verified=%s",
            self.tenant_id,
            self.conversation_id,
            self.device_id or "(unset)",
            self.frontdesk_surface,
            self.model_key or "(unset)",
            self.person_id or self.person_name or "(anonymous)",
            self.person_identity_verified,
        )

    def set_person_context(
        self,
        *,
        person_id: str,
        person_name: str,
        verified: bool,
        memory_read_allowed: bool | None = None,
        privacy_epoch: int = 0,
    ) -> None:
        """Apply identity from the server-owned person conversation snapshot."""

        previous_memory_binding = self._person_memory_binding()
        person_id = (person_id or "").strip()[:120]
        person_name = (person_name or "").strip()[:80]
        is_verified = bool(verified and person_id and person_name)
        self.person_id = person_id if is_verified else ""
        self.person_name = person_name if is_verified else ""
        self.person_identity_verified = is_verified
        self.person_memory_read_allowed = bool(
            is_verified
            and (is_verified if memory_read_allowed is None else memory_read_allowed)
        )
        self.person_privacy_epoch = max(0, int(privacy_epoch or 0))
        current_memory_binding = self._person_memory_binding()
        if current_memory_binding != previous_memory_binding:
            self._person_memory_prompt = ""
            self._person_memory_loaded_for = None
            logger.info(
                "人物长期记忆会话快照已失效: conversation=%s previous=%s current=%s",
                self.conversation_id,
                previous_memory_binding or "(none)",
                current_memory_binding or "(none)",
            )
        logger.info(
            "语音流可信人物上下文已更新: conversation=%s person=%s name=%s verified=%s memory_read=%s privacy_epoch=%d",
            self.conversation_id,
            self.person_id or "(anonymous)",
            self.person_name or "(unknown)",
            self.person_identity_verified,
            self.person_memory_read_allowed,
            self.person_privacy_epoch,
        )

    async def finish_audio(self) -> None:
        async with self._turn_lock:
            turn_started_at = time.perf_counter()
            reason = "ok"
            try:
                await self.asr.send_audio(b"", is_last=True)
                final_text = await self._wait_for_asr_end()
                final_text = final_text.strip()
                asr_ms = (time.perf_counter() - turn_started_at) * 1000
                if not final_text:
                    reason = "empty_asr"
                    logger.info("语音轮次结束: reason=empty_asr asr_ms=%.0f", asr_ms)
                    return
                logger.info("语音 ASR 最终结果: chars=%d asr_ms=%.0f text=%s", len(final_text), asr_ms, final_text)
                await self._send({"type": "asr_final", "text": final_text})
                silence = await self._handle_dialog_silence_control(final_text)
                if silence.handled:
                    reason = silence.reason
                    return
                final_text = silence.route_text
                wake = await self._handle_assistant_wake_name(final_text)
                if wake.wake_only:
                    return
                route_text = wake.command_text
                if await self._handle_person_memory_command(route_text):
                    return
                if await self._handle_person_context_intent(route_text):
                    return
                if await self._handle_voice_action(route_text):
                    return
                await self._run_llm_and_tts(route_text)
            except Exception as exc:
                reason = "error"
                logger.exception("Voice pipeline turn failed: %s", exc)
                await self._send_error(str(exc))
            finally:
                logger.info(
                    "语音轮次完成: reason=%s total_ms=%.0f",
                    reason,
                    (time.perf_counter() - turn_started_at) * 1000,
                )
                await self._send_done(reason)

    async def close(self) -> None:
        self._closed = True
        if self._asr_task is not None:
            self._asr_task.cancel()
            try:
                await self._asr_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.info("Voice pipeline ASR receive task closed with error: %s", exc)
        await self.asr.close()

    async def _send(self, payload: dict) -> bool:
        if self._closed:
            return False
        try:
            await self.send_json(payload)
            return True
        except Exception as exc:
            self._closed = True
            logger.info(
                "Voice pipeline client send skipped after disconnect: type=%s error=%s",
                payload.get("type"),
                exc,
            )
            return False

    async def _wait_for_asr_end(self) -> str:
        text = ""
        while True:
            event = await self._asr_events.get()
            if event.get("type") == "asr":
                text = event.get("text") or text
                if not await self._send(
                    {
                        "type": "asr_partial",
                        "text": text,
                        "final": bool(event.get("final")),
                    }
                ):
                    return text
            elif event.get("type") == "asr_end":
                return event.get("text") or text

    async def _drain_asr_events(self, *, block: bool) -> None:
        while True:
            try:
                event = await self._asr_events.get() if block else self._asr_events.get_nowait()
            except asyncio.QueueEmpty:
                return
            if event.get("type") == "asr":
                if not await self._send(
                    {
                        "type": "asr_partial",
                        "text": event.get("text") or "",
                        "final": bool(event.get("final")),
                    }
                ):
                    return
            elif event.get("type") == "asr_end":
                await self._asr_events.put(event)
                return

    async def _run_llm_and_tts(self, user_text: str) -> None:
        llm_started_at = time.perf_counter()
        contextual_text = self._build_contextual_user_text(user_text)
        if self._person_memory_prompt:
            contextual_text = f"{self._person_memory_prompt}\n\n{contextual_text}"
        token_queue = stream_llm_to_async_queue(contextual_text, self.tenant_id)
        sentence_buffer = ""
        full_answer = ""
        sentence_index = 0
        first_token_logged = False
        if not await self._send({"type": "llm_start"}):
            return

        while True:
            if self._closed:
                return
            token = await token_queue.get()
            if token is None:
                break
            if not first_token_logged:
                first_token_logged = True
                logger.info(
                    "语音 LLM 首 token: first_token_ms=%.0f text=%s",
                    (time.perf_counter() - llm_started_at) * 1000,
                    user_text,
                )
            full_answer += token
            sentence_buffer += token
            if not await self._send({"type": "llm_delta", "text": token}):
                return

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

        await self._send({"type": "llm_end", "text": full_answer.strip()})
        if full_answer.strip():
            self._last_completed_turn = (user_text, full_answer.strip())
        logger.info(
            "语音 LLM+TTS 完成: chars=%d sentences=%d total_ms=%.0f text=%s",
            len(full_answer.strip()),
            sentence_index,
            (time.perf_counter() - llm_started_at) * 1000,
            user_text,
        )

    async def _handle_assistant_wake_name(self, user_text: str) -> WakeNameResult:
        persona = await self._resolve_avatar_persona()
        wake = parse_wake_name(
            user_text,
            assistant_name=persona.assistant_name,
            wake_aliases=persona.wake_aliases,
        )
        if not wake.called:
            return wake
        logger.info(
            "语音唤名命中: conversation=%s assistant=%s alias=%s wake_only=%s original=%s routed=%s",
            self.conversation_id,
            wake.assistant_name,
            wake.matched_alias,
            wake.wake_only,
            wake.original_text,
            wake.command_text,
        )
        await self._send(
            {
                "type": "wake_name",
                "assistantName": wake.assistant_name,
                "alias": wake.matched_alias,
                "wakeOnly": wake.wake_only,
                "text": wake.command_text,
            }
        )
        if wake.wake_only:
            spoken = await self._speak_scene_response(
                VOICE_ASSISTANT_WAKE_REPLY,
                command="assistant_wake",
                scene="assistant_wake",
                user_text=user_text,
                response_goal="回应用户正在叫你，让对方知道你在听。",
                constraints=["不要展开介绍自己。"],
            )
            self._last_completed_turn = (user_text, spoken)
        return wake

    async def _handle_dialog_silence_control(
        self,
        user_text: str,
    ) -> DialogSilenceHandling:
        persona = await self._resolve_avatar_persona()
        stored_state = get_dialog_silence_state_store().get(
            self.tenant_id,
            self.device_id,
        )
        if stored_state.muted:
            self._dialog_silenced = True
            self._dialog_silence_status_text = stored_state.status_text
        result = resolve_dialog_silence(
            user_text,
            muted=self._dialog_silenced or stored_state.muted,
            assistant_name=persona.assistant_name,
            wake_aliases=persona.wake_aliases,
        )
        if result.action == ACTION_NONE:
            return DialogSilenceHandling(False, result.route_text or user_text)
        if result.action == ACTION_MUTE:
            self._dialog_silenced = True
            self._dialog_silence_status_text = result.status_text
            get_dialog_silence_state_store().set_muted(
                tenant_id=self.tenant_id,
                device_id=self.device_id,
                assistant_name=result.assistant_name,
                status_text=result.status_text,
            )
            logger.info(
                "语音业务静音已开启: conversation=%s tenant=%s device=%s assistant=%s trigger=%s",
                self.conversation_id,
                self.tenant_id,
                self.device_id or "(unset)",
                result.assistant_name,
                user_text,
            )
            await self._before_dialog_silence_control_response(result)
            await self._send_dialog_silence_state(result, active=True)
            await self._speak_scene_response(
                result.response_text,
                command="dialog_silence:mute",
                scene="dialog_silence_mute",
                user_text=user_text,
                required_facts=[
                    f"已开启静音；需要时喊{result.assistant_name}唤醒。",
                ],
                response_goal="确认数字人进入静音状态，并说明如何唤醒。",
            )
            return DialogSilenceHandling(
                True,
                "",
                reason="dialog_silenced",
                status_text=result.status_text,
            )
        if result.action == ACTION_SUPPRESS:
            self._dialog_silence_status_text = result.status_text
            get_dialog_silence_state_store().set_muted(
                tenant_id=self.tenant_id,
                device_id=self.device_id,
                assistant_name=result.assistant_name,
                status_text=result.status_text,
            )
            logger.info(
                "语音业务静音中忽略实时沟通: conversation=%s tenant=%s device=%s assistant=%s text=%s",
                self.conversation_id,
                self.tenant_id,
                self.device_id or "(unset)",
                result.assistant_name,
                user_text,
            )
            await self._before_dialog_silence_control_response(result)
            await self._send_dialog_silence_state(result, active=True)
            return DialogSilenceHandling(
                True,
                "",
                reason="dialog_silenced",
                status_text=result.status_text,
            )
        if result.action == ACTION_WAKE:
            self._dialog_silenced = False
            self._dialog_silence_status_text = ""
            get_dialog_silence_state_store().clear(self.tenant_id, self.device_id)
            logger.info(
                "语音业务静音已唤醒: conversation=%s tenant=%s device=%s assistant=%s alias=%s route_text=%s",
                self.conversation_id,
                self.tenant_id,
                self.device_id or "(unset)",
                result.assistant_name,
                result.matched_alias,
                result.route_text,
            )
            if not result.route_text:
                await self._before_dialog_silence_control_response(result)
            await self._send_dialog_silence_state(result, active=False)
            if result.route_text:
                return DialogSilenceHandling(
                    False,
                    result.route_text,
                    status_text=result.status_text,
                    resumed=True,
                )
            await self._speak_scene_response(
                result.response_text,
                command="dialog_silence:wake",
                scene="dialog_silence_wake",
                user_text=user_text,
                required_facts=["已解除静音，数字人正在听。"],
                response_goal="自然告诉用户已恢复响应。",
            )
            return DialogSilenceHandling(
                True,
                "",
                reason="dialog_resumed",
                status_text=result.status_text,
                resumed=True,
            )
        return DialogSilenceHandling(False, user_text)

    async def _before_dialog_silence_control_response(
        self,
        result: DialogSilenceResult,
    ) -> None:
        del result
        return None

    async def _send_dialog_silence_state(
        self,
        result: DialogSilenceResult,
        *,
        active: bool,
    ) -> None:
        await self._send(
            {
                "type": "dialog_silence",
                "active": active,
                "assistantName": result.assistant_name,
                "matchedAlias": result.matched_alias,
                "statusText": result.status_text,
                "responseText": result.response_text,
            }
        )

    async def _resolve_avatar_persona(self):
        return await asyncio.to_thread(
            get_tenant_avatar_persona_service().resolve,
            self.tenant_id,
        )

    async def _handle_person_context_intent(self, user_text: str) -> bool:
        person_reply = self.person_context_intent_router.route(
            user_text,
            person_name=self.person_name,
            identity_verified=self.person_identity_verified,
            context=self._person_memory_context or self._context,
        )
        if person_reply is None:
            return False
        logger.info(
            "Cascade 人物上下文意图命中: conversation=%s intent=%s verified=%s person=%s context_messages=%d",
            self.conversation_id,
            person_reply.intent,
            person_reply.identity_verified,
            self.person_name or "(unknown)",
            person_reply.source_messages,
        )
        required_facts = list(person_reply.required_facts or (person_reply.text,))
        try:
            spoken = await self._speak_scene_response(
                "",
                command=person_reply.intent,
                scene=person_reply.intent,
                user_text=user_text,
                required_facts=required_facts,
                response_goal=person_reply.response_goal
                or "按可信人物上下文回答用户问题。",
                user_info={
                    "person_name": self.person_name,
                    "identity_verified": str(self.person_identity_verified),
                },
                constraints=[
                    *person_reply.constraints,
                    "先理解用户问题再组织回答，不要把事实材料当成逐字稿念出来。",
                ],
            )
        except Exception as exc:
            logger.warning(
                "Cascade 人物上下文动态话术不可用: conversation=%s tenant=%s intent=%s error_type=%s error=%s",
                self.conversation_id,
                self.tenant_id,
                person_reply.intent,
                type(exc).__name__,
                exc,
            )
            spoken = self._person_context_scene_unavailable_text(person_reply)
            await self._speak_command_response(spoken, command=person_reply.intent)
        self._last_completed_turn = (user_text, spoken)
        return True

    async def _handle_person_memory_command(self, user_text: str) -> bool:
        command = route_person_memory_command(user_text)
        if command is None:
            return False
        memory_changed = False
        if not self.person_identity_verified or not self.person_id:
            response = "我还没有确认你的身份，暂时不能操作个人记忆。"
        elif not self.person_memory_read_allowed:
            response = "当前人物会话暂时不可用，请稍后再试。"
        else:
            service = get_person_memory_service()
            if command.action == "remember":
                try:
                    await asyncio.to_thread(
                        service.remember_explicit,
                        person_id=self.person_id,
                        conversation_id=self.conversation_id,
                        content=command.content,
                    )
                    response = "好的，我已经把这件事记在你的个人记忆里了。"
                    memory_changed = True
                except Exception:
                    logger.exception(
                        "显式人物记忆写入失败: conversation=%s person=%s",
                        self.conversation_id,
                        self.person_id,
                    )
                    response = "这次没有记成功，我已经记录了错误，请稍后再试。"
            elif command.action == "arrival_task":
                target_name = (command.target_name or self.person_name).strip()
                if not target_name:
                    response = "我还没有确认要对谁设置这个到场提醒。"
                else:
                    try:
                        target_person_id = (
                            self.person_id
                            if not command.target_name
                            else await asyncio.to_thread(
                                get_person_identity_repository().resolve_person_id,
                                target_name,
                                self.tenant_id,
                            )
                        )
                        result = await asyncio.to_thread(
                            service.upsert_arrival_speech_task,
                            tenant_id=self.tenant_id,
                            creator_person_id=self.person_id,
                            creator_name=self.person_name,
                            target_person_id=target_person_id,
                            target_name=target_name,
                            content=command.content,
                            exact_text=command.exact,
                            repeat=command.repeat,
                            actor="voice-command",
                        )
                        response = self._arrival_task_response(
                            target_name=target_name,
                            is_self=not command.target_name,
                            content=str(result.get("content") or command.content),
                            exact=command.exact,
                            repeat=command.repeat,
                        )
                    except Exception:
                        logger.exception(
                            "人物到场任务写入失败: conversation=%s creator=%s target=%s",
                            self.conversation_id,
                            self.person_id,
                            target_name,
                        )
                        response = "这个到场提醒没有设置成功，我已经记录了错误，请稍后再试。"
            elif command.action == "cancel_arrival_task":
                try:
                    if command.content == "self":
                        target_person_id = self.person_id
                        latest_only = False
                    else:
                        target_person_id = ""
                        latest_only = True
                    result = await asyncio.to_thread(
                        service.cancel_arrival_speech_tasks,
                        tenant_id=self.tenant_id,
                        creator_person_id=self.person_id,
                        target_person_id=target_person_id,
                        latest_only=latest_only,
                        actor="voice-command",
                        reason=command.content or "voice_cancel_arrival_task",
                    )
                    cancelled = int(result.get("cancelled") or 0)
                    if cancelled > 0:
                        response = "好的，已经取消这个到场提醒。之后会恢复普通的再次到场问候。"
                    else:
                        response = "我没有找到正在生效的到场提醒。"
                except Exception:
                    logger.exception(
                        "人物到场任务取消失败: conversation=%s creator=%s mode=%s",
                        self.conversation_id,
                        self.person_id,
                        command.content,
                    )
                    response = "这个到场提醒暂时没有取消成功，我已经记录了错误，请稍后再试。"
            elif command.action in {"request_forget", "request_clear"}:
                result = await asyncio.to_thread(
                    service.request_forget,
                    confirmation_id=self.conversation_id,
                    person_id=self.person_id,
                    query=command.content,
                    clear_all=command.action == "request_clear",
                )
                if not result["factIds"] and not result["clearAll"]:
                    response = "我没有找到与你描述相符的个人记忆。"
                    service.cancel_confirmation(self.conversation_id)
                elif result["clearAll"]:
                    response = "这会清空你的全部个人画像和记忆事实。请再说一次“确认”后我才会执行。"
                else:
                    preview = "；".join(
                        str(item.get("content") or "")[:40]
                        for item in result["matches"][:2]
                    )
                    response = f"我找到这些相关记忆：{preview}。如果确定删除，请再说一次“确认”。"
            elif command.action == "confirm_forget":
                result = await asyncio.to_thread(
                    service.confirm_forget,
                    confirmation_id=self.conversation_id,
                    person_id=self.person_id,
                )
                if not result.get("confirmed"):
                    response = "没有等待确认的删除操作，或者确认已经超时。"
                elif result.get("clearAll"):
                    response = "已经清空你的个人画像和记忆事实。"
                    memory_changed = True
                else:
                    response = f"已经删除 {int(result.get('factsRetracted') or 0)} 条个人记忆。"
                    memory_changed = int(result.get("factsRetracted") or 0) > 0
            else:
                service.cancel_confirmation(self.conversation_id)
                response = "好的，已经取消删除个人记忆。"

        if memory_changed:
            await self.load_person_memory_context(force=True)
            self._on_person_memory_snapshot_changed()

        logger.info(
            "人物记忆语音命令完成: conversation=%s action=%s person=%s",
            self.conversation_id,
            command.action,
            self.person_id or "(anonymous)",
        )
        spoken = await self._speak_scene_response(
            response,
            command=f"person_memory:{command.action}",
            scene=f"person_memory_{command.action}",
            user_text=user_text,
            required_facts=[response],
            response_goal="自然告知个人记忆或到场提醒命令的处理结果。",
            user_info={
                "person_name": self.person_name,
                "person_id": self.person_id,
            },
            constraints=[
                "不能改变是否成功、是否需要确认、取消数量或错误状态。",
            ],
        )
        self._last_completed_turn = (user_text, spoken)
        return True

    @staticmethod
    def _arrival_task_response(
        *,
        target_name: str,
        is_self: bool,
        content: str,
        exact: bool,
        repeat: bool,
    ) -> str:
        content = (content or "").strip()
        if is_self:
            if exact:
                return f"好的，以后你一过来我就跟你说：{content}"
            return f"好的，以后你一过来我会按这个要求提醒你：{content}"
        timing = "以后" if repeat else "待会儿"
        if exact:
            return f"好的，{timing}{target_name}过来时我会跟他说：{content}"
        return f"好的，{timing}{target_name}过来时我会按这个要求提醒他：{content}"

    def _person_memory_binding(self) -> tuple[str, int] | None:
        if not self.person_memory_read_allowed or not self.person_id:
            return None
        return self.person_id, self.person_privacy_epoch

    async def load_person_memory_context(self, *, force: bool = False) -> str:
        """Load a trusted person's bounded memory snapshot once per binding."""

        binding = self._person_memory_binding()
        if binding is None:
            self._person_memory_prompt = ""
            self._person_memory_loaded_for = None
            return ""
        if not force and self._person_memory_loaded_for == binding:
            logger.debug(
                "人物长期记忆复用会话快照: conversation=%s person=%s chars=%d",
                self.conversation_id,
                self.person_id,
                len(self._person_memory_prompt),
            )
            return self._person_memory_prompt

        async with self._person_memory_load_lock:
            binding = self._person_memory_binding()
            if binding is None:
                self._person_memory_prompt = ""
                self._person_memory_loaded_for = None
                return ""
            if not force and self._person_memory_loaded_for == binding:
                return self._person_memory_prompt

            started_at = time.perf_counter()
            try:
                context = await asyncio.to_thread(
                    get_person_memory_service().build_session_context,
                    person_id=self.person_id,
                    memory_read_allowed=self.person_memory_read_allowed,
                )
            except Exception:
                logger.exception(
                    "人物长期记忆会话快照读取异常: conversation=%s person=%s",
                    self.conversation_id,
                    self.person_id,
                )
                return self._person_memory_prompt

            if binding != self._person_memory_binding():
                logger.warning(
                    "人物长期记忆会话快照因身份变化被丢弃: conversation=%s loaded_for=%s current=%s",
                    self.conversation_id,
                    binding,
                    self._person_memory_binding() or "(none)",
                )
                return self._person_memory_prompt

            self._person_memory_prompt = context
            self._person_memory_loaded_for = binding
            logger.info(
                "人物长期记忆会话快照已加载: conversation=%s person=%s chars=%d elapsed_ms=%.0f force=%s",
                self.conversation_id,
                self.person_id,
                len(context),
                (time.perf_counter() - started_at) * 1000,
                force,
            )
            return context

    def _on_person_memory_snapshot_changed(self) -> None:
        """Hook for persistent model transports that must refresh their prompt."""

        return None

    async def _handle_voice_action(self, user_text: str) -> bool:
        route_started_at = time.perf_counter()
        proposal = self.command_router.route(user_text)
        if proposal is None:
            proposal = self.agent_intent_router.route(user_text, self._context)
        if proposal is None:
            logger.info(
                "语音动作分流: 未命中工具动作，进入普通对话 route_ms=%.0f text=%s",
                (time.perf_counter() - route_started_at) * 1000,
                user_text,
            )
            return False

        logger.info(
            "语音动作分流: 命中 action=%s source=%s route_ms=%.0f text=%s",
            proposal.action,
            proposal.source,
            (time.perf_counter() - route_started_at) * 1000,
            user_text,
        )
        return await self._execute_voice_action(proposal, user_text)

    async def _execute_voice_action(self, proposal: DialogActionProposal, user_text: str) -> bool:
        result = self.action_executor.execute(
            proposal,
            user_text=user_text,
            conversation_id=self.conversation_id,
            device_id=self.device_id,
            tenant_id=self.tenant_id,
        )
        if not result.handled:
            logger.info(
                "语音动作分流: proposal 未执行，进入普通对话 action=%s status=%s text=%s",
                proposal.action,
                result.status,
                user_text,
            )
            return False

        logger.info(
            "Voice pipeline action handled: action=%s status=%s task=%s payload=%s",
            result.action,
            result.status,
            result.task_id,
            result.payload,
        )
        await self._send(
            {
                "type": "command_executed",
                "action": result.action,
                "status": result.status,
                "task_id": result.task_id,
                "payload": result.payload,
                "source": proposal.source,
                "confidence": proposal.confidence,
            }
        )
        if result.agent_signal:
            await self._send(result.agent_signal)

        if not result.response:
            return True
        spoken = await self._speak_action_result(result, user_text=user_text)
        self._last_completed_turn = (user_text, spoken or result.response)
        return True

    async def _speak_action_result(
        self,
        result: DialogActionExecution,
        *,
        user_text: str,
    ) -> str:
        response = result.response
        if self._is_volume_adjustment_result(result):
            logger.info("音量动作即时语音确认: action=%s task=%s", result.action, result.task_id)
            await self._speak_scene_response(
                self._volume_adjustment_feedback_text(result),
                command=result.action,
                scene=f"{result.action}_progress",
                user_text=user_text,
                required_facts=[self._volume_adjustment_feedback_text(result)],
                response_goal="先让用户知道正在执行音量调整。",
                constraints=["不要说调整已经最终完成。"],
            )
        task_status = await self._wait_for_audible_action_effect(result)
        if task_status == "failed":
            response = "我试着调整系统音量，但前台设备没有执行成功。"
        elif task_status == "timeout":
            response = "我已经把调音量指令发给前台设备，请你再听一下。"
        spoken = await self._speak_scene_response(
            response,
            command=result.action,
            scene=result.action,
            user_text=user_text,
            required_facts=[response],
            response_goal="自然告知语音动作的执行结果。",
            constraints=[
                "不能改变动作是否成功、是否等待输入、是否超时或失败。",
            ],
        )
        if self._is_volume_adjustment_result(result):
            logger.info(
                "音量动作已并入当前语音会话: conversation=%s action=%s status=%s response=%s",
                self.conversation_id,
                result.action,
                task_status or "executed",
                spoken,
            )
        return spoken

    def _is_volume_adjustment_result(self, result: DialogActionExecution) -> bool:
        return result.action in {ACTION_ADJUST_SYSTEM_VOLUME, ACTION_ADJUST_VOLUME}

    def _volume_adjustment_feedback_text(self, result: DialogActionExecution) -> str:
        style = str(result.payload.get("response_style") or "")
        if style == "now_check":
            return "那我继续为你调整。"
        return "正在为你调节音量。"

    async def _speak_command_response(self, response: str, *, command: str) -> float:
        if not await self._send({"type": "llm_start", "command": command}):
            return 0.0
        await self._send({"type": "llm_delta", "text": response})
        audio_seconds = await self._synthesize_sentence(response, 1)
        await self._send({"type": "llm_end", "text": response, "command": command})
        return audio_seconds

    async def _speak_scene_response(
        self,
        canonical_text: str,
        *,
        command: str,
        scene: str,
        user_text: str = "",
        required_facts: list[str] | None = None,
        response_goal: str = "",
        user_info: dict | None = None,
        constraints: list[str] | None = None,
    ) -> str:
        spoken = await self._generate_scene_reply(
            canonical_text,
            scene=scene,
            user_text=user_text,
            required_facts=required_facts,
            response_goal=response_goal,
            user_info=user_info,
            constraints=constraints,
        )
        await self._speak_command_response(spoken, command=command)
        return spoken

    async def _generate_scene_reply(
        self,
        canonical_text: str,
        *,
        scene: str,
        user_text: str = "",
        required_facts: list[str] | None = None,
        response_goal: str = "",
        user_info: dict | None = None,
        constraints: list[str] | None = None,
    ) -> str:
        facts = list(required_facts or [])
        if canonical_text and canonical_text not in facts:
            facts.insert(0, canonical_text)
        try:
            return await asyncio.to_thread(
                get_dialog_chat_service().scene_reply,
                scene=scene,
                user_text=user_text,
                tenant_id=self.tenant_id,
                context=self._context,
                user_info=user_info
                or {
                    "person_name": self.person_name,
                    "identity_verified": str(self.person_identity_verified),
                    "device_id": self.device_id,
                },
                required_facts=facts,
                response_goal=response_goal,
                constraints=constraints or [],
            )
        except Exception:
            logger.exception(
                "动态场景话术生成失败: conversation=%s tenant=%s scene=%s canonical_chars=%d",
                self.conversation_id,
                self.tenant_id,
                scene,
                len(canonical_text or ""),
            )
            raise

    def _person_context_scene_unavailable_text(self, person_reply) -> str:
        if person_reply.intent == "person_identity":
            if person_reply.identity_verified and self.person_name:
                return f"我已经确认到你是{self.person_name}，但现在没法把回答组织得更自然，请稍后再试。"
            return "我现在还不能确认你的身份，暂时不能读取个人信息。请正对摄像头停留一下。"
        if not person_reply.identity_verified:
            return "我现在还不能确认你的身份，暂时不能读取个人对话记录。请先完成识别。"
        if person_reply.needs_clarification:
            return "我刚才没能把澄清问题组织出来，请你再说一遍想回忆哪段对话。"
        return "我现在没法整理之前的对话，当前对话模型暂时不可用，请稍后再试。"

    async def _wait_for_audible_action_effect(self, result) -> str:
        if result.action != ACTION_ADJUST_SYSTEM_VOLUME or not result.task_id:
            return ""
        timeout = max(0.0, VOICE_SYSTEM_VOLUME_TASK_WAIT_SECONDS)
        if timeout <= 0:
            return ""
        logger.info(
            "语音动作等待客户端生效: action=%s task=%s timeout=%.1fs",
            result.action,
            result.task_id,
            timeout,
        )
        task = await asyncio.to_thread(
            get_client_task_queue().wait_for_terminal,
            result.task_id,
            timeout=timeout,
            tenant_id=self.tenant_id,
        )
        if task is None:
            logger.warning("语音动作等待客户端生效失败: task=%s not_found", result.task_id)
            return "failed"
        if task.status == "done":
            logger.info(
                "语音动作客户端已生效: action=%s task=%s result=%s",
                result.action,
                result.task_id,
                task.result,
            )
            return "done"
        if task.status == "failed":
            logger.warning(
                "语音动作客户端执行失败: action=%s task=%s error=%s",
                result.action,
                result.task_id,
                task.error,
            )
            return "failed"
        logger.warning(
            "语音动作等待客户端生效超时: action=%s task=%s status=%s timeout=%.1fs",
            result.action,
            result.task_id,
            task.status,
            timeout,
        )
        return "timeout"

    def _build_contextual_user_text(self, user_text: str) -> str:
        if not self._context:
            return user_text
        lines = ["以下是本轮语音对话的上下文。请结合上下文理解用户追问，但优先回答最后一句。"]
        for item in self._context:
            label = "用户" if item["role"] == "user" else "助手"
            lines.append(f"{label}: {item['content']}")
        lines.append(f"用户最新问题: {user_text}")
        return "\n".join(lines)

    async def _synthesize_sentence(self, text: str, index: int) -> float:
        text = normalize_tts_text(text)
        if not text:
            return 0.0
        tts_started_at = time.perf_counter()
        if not await self._send(
            {"type": "tts_start", "index": index, "text": text, "mime": self.tts.mime_type}
        ):
            return 0.0
        duration_seconds = 0.0
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
            duration_seconds = float(metadata.get("duration_ms") or 0) / 1000.0
            logger.info(
                "TTS sentence audio ready: index=%s chars=%s mime=%s chunks=%s bytes=%s duration_ms=%s synth_ms=%.0f",
                index,
                len(text),
                self.tts.mime_type,
                len(chunks),
                len(audio),
                metadata.get("duration_ms"),
                (time.perf_counter() - tts_started_at) * 1000,
            )
            await self._send(
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
            await self._send({"type": "tts_end", "index": index})
        return duration_seconds

    async def _send_error(self, message: str, *, recoverable: bool = False) -> None:
        if self._closed:
            return
        await self._send(
            {
                "type": "error",
                "message": message,
                "recoverable": recoverable,
            }
        )

    async def _send_done(self, reason: str = "ok", extra: dict | None = None) -> None:
        if self._closed or self._terminal_sent:
            return
        self._terminal_sent = True
        payload = {"type": "done"}
        if reason != "ok":
            payload["reason"] = reason
        if self._dialog_silenced and self._dialog_silence_status_text:
            payload["dialogSilenced"] = True
            payload["statusText"] = self._dialog_silence_status_text
        if extra:
            payload.update(extra)
        await self._send(payload)


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


def stream_llm_to_async_queue(
    user_text: str, tenant_id: str = DEFAULT_TENANT_ID
) -> asyncio.Queue[str | None]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def worker() -> None:
        try:
            for token in get_dialog_chat_service().stream_reply(
                user_text, tenant_id
            ):
                loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception as exc:
            logger.exception("LLM stream failed: %s", exc)
            loop.call_soon_threadsafe(queue.put_nowait, "对不起，我刚刚思考时出错了，请再问我一次。")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = loop.create_task(asyncio.to_thread(worker))
    task.add_done_callback(lambda item: item.exception() if item.exception() else None)
    return queue
