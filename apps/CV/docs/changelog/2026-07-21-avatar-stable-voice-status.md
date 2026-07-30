# 2026-07-21 流式语音播放期间状态栏保持稳定

## 问题

用户询问“介绍你们公司”这类长回答时，后端只生成一段 RAG 语音，但 avatar 前端会在播放期间按音频进度把长回答切成短片段写入主状态栏。长回答播放时状态栏文字每 250ms 检查一次并切换片段，观感像文字来回跳转。

## 根因

主状态栏同时承担“系统状态”和“回答片段字幕”两种职责。对于长 RAG 回答，`updateStreamingSpeechStatus()` 会根据 `audio.currentTime / durationMs` 计算当前短句并反复 `showStatus()`，导致状态文案频繁变化。

## 修改

- 流式语音播放期间，主状态栏固定显示 `叮当正在说话`。
- 回答文本仍保留在语音对话文本/控制状态里，不影响音频播放、播放完成确认、抢话上下文和人物记忆提交。

## 验证

```powershell
node --check server_deploy/avatar/avatar.js
node --test server_deploy/avatar/tests/voice_turn_policy.test.js
node --test server_deploy/avatar/tests/tenant_state.test.js
```

结果：语法检查通过，avatar 语音策略测试 14 条通过，租户状态测试 3 条通过。
