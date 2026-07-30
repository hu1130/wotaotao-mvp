# 2026-07-22

## 问题

数字人说话被空打断后继续回答，最后一句播放完成时只清理了底部语音文本，状态栏仍可能停留上一句播放状态。

## 原因

空打断恢复回答复用了 `playRawTTS` 的本地对话播放路径。该路径在播放结束时默认只调用 `clearVoiceChatText()` 和清空 assistant 文本，没有同步调用 `clearStatusBeforeDeferredSpeech()`，因此状态栏没有和正常实时沟通完成流程一样立即清理。

## 修改方案

- 给空打断恢复回答传入 `clearSpeechDisplayOnEnd`。
- `playRawTTS` 在该标记下播放结束立即调用 `clearStreamingSpeechDisplay()`，同步清理状态栏、语音文本和说话文本。
- 空打断恢复的 finally 收尾也改为清完整 speech display，避免播放 Promise 结束后的状态残留。

## 影响

仅影响空打断恢复回答的播放结束清理。固定语音、实时流式对话和普通本地 TTS 的其它结束策略不变。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `npm test`（server_deploy/avatar）
- `python scripts/check-runtime-boundaries.py`
