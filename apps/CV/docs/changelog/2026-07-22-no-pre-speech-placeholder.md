# 2026-07-22

## 去除开口前的准备态闪烁

### 根因

前台状态栏没有 `正在准备说话` 这个精确文案，但还有两个同类前置状态会在音频真正播放前同步到前台壳层：

- 固定语音 `playTTS()` 在字幕加载完成后立即广播 `assistantSpeechText`。
- 实时语音 `tts_start` 在音频到达前写入 `voiceChatText="正在合成语音"`。

这些状态不是实际朗读文本，但会被前台壳层当作状态内容短暂显示，表现成数字人做动作、开口前状态栏闪一下。

### 修改

- 固定语音只在浏览器音频进入 `playing` 后广播 `assistantSpeechText`。
- 移除实时语音 `tts_start` 阶段的 `正在合成语音` 文案。
- 保留实际播放后的逐句状态同步。
- 更新 avatar 脚本版本号，避免浏览器沿用旧 `avatar.js`。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
