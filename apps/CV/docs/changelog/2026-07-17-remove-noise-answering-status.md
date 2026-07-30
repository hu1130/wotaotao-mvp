# 2026-07-17 移除噪音触发后的正在回答状态

## 问题

环境噪音偶发触发前端 VAD，停收音后一段时间状态栏会显示“正在回答”。噪音本身没有有效语义，展示回答或思考类等待文案会显得不自然。

## 原因

前端在本地 VAD 静音结束和手动结束收音时调用 `finishVoiceTurn('正在回答')`。服务端 VAD 判停时也会写入“已检测到你说完，正在回答”。同时播放音频但尚未拿到文本时，`speaking` 状态默认回退到“正在回答”。

## 修改方案

- 本地 VAD 停收音只发送 `stop`，不主动刷新状态栏等待文案。
- 服务端 VAD 判停只清理输入状态和记录日志，不显示“正在回答”。
- `speaking` 阶段无文本时返回空字符串，避免无内容音频或迟到文本阶段回退到“正在回答”。

## 影响

真正的识别文本、模型思考、回答文本和音频字幕仍由 ASR/LLM/TTS 事件驱动展示。噪音触发但没有有效内容时，状态栏不再出现“正在回答”。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
