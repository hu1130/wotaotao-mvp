# 2026-07-28

## 问题

静音和解除静音控制反馈仍然会出现状态栏文本与实际语音内容不同步；解除静音还可能出现状态先变化、语音反馈超时的情况。

## 原因

Omni 后端此前把静音/解除静音反馈接到了 `external_rag` 通道，让火山实时模型在音频链路里边生成边播。该通道适合普通知识/人物上下文问答，但控制反馈需要“先确定一份话术，再让状态栏和 TTS 共用同一份文本”。`external_rag` 会带来首音频超时、文本事件与音频绑定不可观测等问题，导致状态栏和语音没有共同的文本真值。

## 修改方案

静音/解除静音反馈改为：

1. 使用现有 Qwen 动态场景话术生成 `_generate_scene_reply()` 生成 `spoken`。
2. 通过 Omni `chat_tts_text` 播放同一个 `spoken`，保持克隆音色链路。
3. 前端继续通过动态 `dialog_silence` 生命周期接收 `llm_delta`，状态栏与语音共用同一份 `spoken`。
4. 移除静音控制专用 `external_rag` payload builder，避免控制指令再次误接入 RAG 型通道。
5. 前端动态反馈等待真实 `llm_delta` 后再展示反馈话术，不再把“已解除静音”或“思考中”当作临时反馈文案。

## 影响

仅影响静音和解除静音反馈。普通实时沟通、知识 RAG、人物记忆上下文仍保持原 Omni 链路。

## 验证

- `python -m py_compile server_deploy/core/speech_streaming/omni.py server_deploy/tests/test_omni_voice.py`
- `python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_feedback_uses_scene_reply_and_omni_tts tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_wake_feedback_uses_scene_reply_and_omni_tts`
- `python -m unittest -v tests.test_dialog_silence`
- `npm test` in `server_deploy/avatar`
