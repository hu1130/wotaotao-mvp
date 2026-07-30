# 2026-07-22

## 问题

固定语录播放时如果被用户打断，后续空识别恢复逻辑可能继续播出上一轮实时回答的内容。按业务设定，固定语录是一次性播报，被打断后不需要恢复。

## 原因

固定语录和实时回答都复用 `cancelCurrentVoiceTurn()`。该函数原本只按“实时回答被打断”理解取消场景，只要当前有音频或旧回答文本，就会调用 `captureEmptyBargeResume()` 缓存恢复内容。固定语录播放时 `activeSpeechOwner` 是 `legacy_tts`，但旧逻辑没有按 owner 区分，导致固定语录取消也可能拿到上一轮 `currentAnswerText` 并进入空打断恢复链路。

## 修改方案

- 在 `voice_turn_policy.js` 增加 `canCaptureInterruptedSpeechForResume()`，明确只有 `local_dialog` 实时回答可以缓存空打断恢复。
- `avatar.js` 取消固定语录时清空空打断恢复缓存，不发送旧实时会话 interrupt，也不写入被打断对话上下文。
- 增加 `fixed speech cancelled without resume` 客户端日志，便于确认固定语录被打断后按一次性播报结束。

## 影响

固定语录被用户打断后不会再恢复上一轮回答。实时回答被空打断后的续播或重新生成逻辑保持不变。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python scripts/check-runtime-boundaries.py`
