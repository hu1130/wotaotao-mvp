# 2026-07-22

## 问题

数字人正在说话时被用户打断，状态栏没有切换到“你说，我听着~”，而是继续停留在被打断时的说话文本。

## 原因

打断流程先显示“你说，我听着”，再执行旧语音清理。这个顺序依赖 `clearStatusBeforeDeferredSpeech()` 的保护逻辑保留打断提示；同时保护判断使用未格式化常量，和实际写入状态栏的文本不完全同源，导致状态更新容易被旧清理流程覆盖或失效。

## 修改方案

- 将打断提示改为“你说，我听着~”。
- 打断时先停止/清理旧语音，再显示打断提示，避免旧 speaking 状态覆盖新 listening 状态。
- `isInterruptedListeningStatusProtected()` 改为使用同一个 `voiceTurnPolicy.statusText()` 结果判断，保证显示与保护一致。

## 影响

影响实时语音回答和可打断固定语音被用户打断后的状态栏显示。不改变空打断恢复回答的记忆、续答、TTS 或音频播放逻辑。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `npm test`（server_deploy/avatar）
- `python scripts/check-runtime-boundaries.py`
