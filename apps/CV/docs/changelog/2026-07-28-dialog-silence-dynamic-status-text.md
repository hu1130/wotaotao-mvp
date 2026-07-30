# 2026-07-28

## 问题

静音和解除静音的语音反馈已经改为火山 Omni 动态生成后，状态栏在反馈播放期间仍显示旧的本地静音话术。

## 原因

后端 `dialog_silence` 状态事件仍带着 `resolve_dialog_silence()` 生成的 `responseText`。前端收到该事件后立即用 `responseText` 进入反馈展示态，而真正的 Omni 动态文本稍后才通过 `llm_delta`、`tts_start` 和 `tts_audio` 到达。前端的静音反馈保护逻辑又会在首段音频到达前保护这段旧文本，导致状态栏与语音内容不同步。

## 修改方案

- Omni 后端的静音/解除静音反馈状态事件不再下发旧 `responseText`，改为 `dynamicFeedback=true`。
- 前端支持动态静音反馈：收到 `dynamicFeedback` 后只进入反馈生命周期，不展示旧占位话术。
- 前端在 `llm_delta`、`tts_start`、`tts_audio` 收到真实 Omni 文本后，刷新状态栏和语音文本区。
- 解除静音反馈完成后，状态栏保留动态反馈文本；静音反馈完成后，恢复常驻“静音中，喊...”状态。
- 更新 `index.html` 中 `avatar.js` 版本号，避免浏览器继续使用旧脚本缓存。

## 影响

影响 Omni 实时链路下静音/解除静音反馈的状态栏展示。非 Omni 级联链路仍使用原有 `responseText` 行为。

## 验证

- `python -m py_compile core/speech_streaming/omni.py tests/test_omni_voice.py`
- `python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_feedback_uses_omni_external_rag_context tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_wake_feedback_uses_omni_external_rag`
- `node --check server_deploy/avatar/avatar.js`
