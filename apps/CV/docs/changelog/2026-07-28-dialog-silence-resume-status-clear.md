# 2026-07-28

## 问题

解除静音反馈语音已经正常播放，但状态栏仍显示“静音中，喊...”。

## 原因

线上日志显示解除静音的 Omni external RAG 返回了音频，但未返回文本：`external_rag chars=0`、`answer_chars=0`。前端因此没有触发动态文本更新。与此同时，旧静音常驻状态没有在 `dialog_resumed` 和 active=false 的反馈生命周期里被强制清理，导致状态栏继续被“静音中”保护逻辑占住。

## 修改方案

- 前端收到 `dialog_resumed` 时立即清空 `voiceDialogSilenced` 和 `voiceDialogSilenceStatusText`。
- 解除静音反馈开始或完成时，再次清理旧静音保护状态，避免旧常驻文案回填。
- 仅对解除静音动态反馈使用 `statusText=已解除静音` 做无文本展示兜底。
- 静音开启反馈仍等待 Omni 动态文本，不把“静音中，喊...”当作反馈阶段口播状态。

## 影响

影响 avatar 前端对 Omni 静音/解除静音反馈的状态栏展示，不改变后端语音生成链路。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `npm test` in `server_deploy/avatar`
- `python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_feedback_uses_omni_external_rag_context tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_wake_feedback_uses_omni_external_rag`
