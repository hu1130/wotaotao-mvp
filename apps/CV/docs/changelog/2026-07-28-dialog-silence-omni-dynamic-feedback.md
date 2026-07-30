# 2026-07-28

## 问题

用户触发数字人静音或喊数字人名字解除静音时，状态栏能更新，但没有语音反馈。日志显示静音控制已命中并更新状态，随后动态场景话术生成走 `DIALOG_CHAT_*` HTTP 模型并返回 DashScope 欠费错误，导致没有进入 TTS。

## 原因

Omni 实时语音会话中的静音控制在路由最前面被服务端消费，反馈语音复用了父类 `_speak_scene_response()`，该方法调用 `DialogChatService.scene_reply()` 生成话术，再做本地 TTS。它没有走当前火山 Omni 实时会话，也没有复用实时沟通的上下文链路，因此会被旧供应商配置影响，并且无法保证反馈话术由 Omni 动态组织。

## 修改方案

- 在 `OmniVoicePipelineSession` 中覆盖静音控制场景的 `_speak_scene_response()`。
- `dialog_silence_mute` 和 `dialog_silence_wake` 不再调用 DashScope 场景话术，而是构建“静音控制动态反馈” external RAG payload，通过火山 Omni `send_external_rag()` 发送。
- payload 只传服务端可信事实、回答目标、最近对话上下文和已加载的人物记忆上下文，要求 Omni 直接自然回应、每次重新组织句子、不要固定模板。
- 保留父类静音状态链：Redis 静音态、状态栏 `dialog_silence` 消息、静音期间 suppress、喊名字唤醒路由均不变。
- 保留关键日志，记录 payload 构建、502 发送、外部音频提交和异常原因。

## 影响

影响浏览器 Omni 实时语音后端的静音与解除静音反馈。普通实时沟通、闲聊、人物记忆上下文、企业知识 RAG 和非 Omni 级联语音链路不改变。

## 验证

- `python -m py_compile core/speech_streaming/omni.py tests/test_omni_voice.py`
- `python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_feedback_uses_omni_external_rag_context tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_wake_feedback_uses_omni_external_rag tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_interrupts_omni_default_generation tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silenced_followup_interrupts_and_drops_default_audio`
