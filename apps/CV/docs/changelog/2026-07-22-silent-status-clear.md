# 2026-07-22

## 清空状态栏改为静默路径

### 根因

动作到语音播放之间仍可能调用 `showStatus('', 'idle')`。虽然这只是清空状态栏，但它会走完整状态栏更新路径，和下一次语音状态显示贴得很近时，视觉上仍会像状态框闪一下。

### 修改

- 将固定语音结束/错误、raw TTS 非本地 owner 清理、流式语音 UI 清理、自动回待机、语音错误自动清理中的空状态显示，统一改成 `clearStatusBeforeDeferredSpeech()`。
- `showStatus()` 现在只用于真正要展示文本的语音状态。
- 更新 avatar 脚本版本号，避免浏览器沿用旧 `avatar.js`。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
