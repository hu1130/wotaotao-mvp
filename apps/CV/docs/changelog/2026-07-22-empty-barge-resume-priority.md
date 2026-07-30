# 2026-07-22

## 修复空插话后恢复回答不显示等待文案

### 根因

空插话恢复回答时，恢复 TTS 使用固定的 `SPEECH_PRIORITY_LOCAL_DIALOG_NORMAL`。但被打断的旧实时语音轮次可能仍保留 `local_dialog` 的高优先级，`requestSpeechTurn()` 在显示 `preparingText` 前就因为优先级较低返回 `false`。

因此直接续播“刚才我接着说...”之前没有机会显示 `我接着想想哈`，并可能退回到 `empty_asr` 的默认状态文案，造成动作/固定语音前状态栏一闪即清。

### 修改

- 空插话直接续播路径使用 `getLocalDialogPriority()`。
- 空插话重新生成路径使用 `getLocalDialogPriority()`。
- 保持 `preparingText: "我接着想想哈"`，确保恢复播放前先显示等待文案。
- 更新 avatar 脚本版本号，避免浏览器沿用旧 `avatar.js`。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
