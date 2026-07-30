# 2026-07-22

## 问题

已签到人员再次入场时，后端已经触发 repeat 并发送 avatar 事件，但 avatar 前端在实时语音长连接打开或空监听状态下把 repeat 当作 stale event 丢弃，导致用户看到 repeat 没有播放。

## 原因

`voice_turn_policy.shouldDropFixedEvent()` 对 repeat 有旧的特殊丢弃规则：只要 `voiceInteractionBusy` 或 `voiceStreamOpen` 为真就直接 drop。这个规则和当前业务设定冲突：repeat 应和 check_in 一样，在空监听时可直接打断并播放。

## 修改方案

- 移除 repeat 的预丢弃逻辑，让 repeat 进入统一 fixed speech 仲裁。
- 保留 `canRunFixedSpeechEvent()` 的真实忙碌判断：有音频播放、真实对话进行中或不可打断时仍不会乱播。
- 更新策略测试，固定 repeat 不因 `voiceStreamOpen` 或空监听而被提前 drop。

## 影响

影响 repeat 固定语音事件。check_in、check_out 和低优先级 stare/crowd 的现有仲裁不变。

## 验证

- `node --check server_deploy/avatar/voice_turn_policy.js`
- `npm test`（server_deploy/avatar）
- `python scripts/check-runtime-boundaries.py`
