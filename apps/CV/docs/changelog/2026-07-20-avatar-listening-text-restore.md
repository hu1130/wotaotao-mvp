# 2026-07-20 恢复数字人监听文字

## 问题

监听状态被改成声音驱动音律后，不符合当前产品要求；音律组件还会占用数字人状态栏显示层，存在覆盖正常说话文本的风险。

## 原因

新增音律同时写入 `#status` 和 `#voice-chat-text`，把原有 `voice_turn_policy.statusText('listening')` 的纯文本策略替换成了 DOM 组件，导致监听态与说话态竞争同一显示区域。

## 修改方案

恢复监听态默认文案为“我在听呢”，监听事件和语音轮次开始时重新走文本展示；删除新增音律 DOM 生成、音量驱动更新逻辑和对应 CSS 样式。

## 影响

仅影响 avatar 前端监听状态展示。语音识别、抢话、TTS 播放、签到签退逻辑不变。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `npm test`（`server_deploy/avatar`）
