# 2026-07-22

## 修复数字人说话前状态框闪烁

### 根因

`playRawTTS()` 为了让文字和语音同步，已经改成等待浏览器音频进入 `playing` 后才显示朗读文本。

但在 TTS 请求发出前，如果没有准备态文案，代码仍调用 `showStatus('', 'idle')` 清空状态栏。这个调用会走完整状态栏显示/隐藏路径和状态广播，在旧状态刚被更新或固定语音刚接管空 listening 时，视觉上会像底部状态框先闪一下再被清掉。

### 修改

- 新增播放等待期专用的静默状态清理。
- TTS 生成/等待阶段不再通过 `showStatus()` 主动切换状态栏。
- 仍然只在音频实际 `playing` 后显示真实朗读文本，保证文字和声音同步出现。
- 更新 avatar 脚本版本号，避免浏览器继续加载旧 `avatar.js`。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
