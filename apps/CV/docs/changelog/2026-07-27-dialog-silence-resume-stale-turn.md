# 静音唤醒状态不再被旧轮次丢弃

## 问题

`computer-mine` 静音状态下喊数字人“小丑”后，现场感觉没有解除静音。

## 原因

服务器日志显示 ASR 识别为 `小丑。`，并且后端已经执行 `语音业务静音已唤醒`，随后普通“你好”也能正常回答。真正问题在 avatar 前端：解除静音的 `dialog_silence active=false` 是跨语音轮次状态消息，但前端按普通语音流消息校验 `turnId`。当后端已进入下一轮时，前端收到上一轮的解除静音状态，会输出 `drop stale voice response` 并丢弃，导致 UI 仍保留静音效果。

## 修改方案

- 在 `voice_turn_policy.js` 新增 `isTurnScopedVoiceMessage()`。
- `dialog_silence` 状态消息不再受单个 voice turn 的 stale `turnId` 拦截。
- 音频、文本、done 等普通语音流消息仍继续按 `turnId` 严格隔离，避免旧音频串入新轮。

## 影响

影响 avatar 前端业务静音状态同步。后端静音状态、唤名解析、实时语音轮次隔离和音频播放仲裁不改变。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
