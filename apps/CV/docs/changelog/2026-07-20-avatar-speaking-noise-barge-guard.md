# 2026-07-20 数字人说话期间抢话防噪

## 问题

数字人正在播放回答或可打断固定语音时，前端 near-end VAD 允许用户抢话。但旧逻辑只要求短时间内能量超过阈值，突发高噪音可能被误判为用户说话，导致数字人正在说的话被中断。

## 原因

播放期抢话分支使用 `VOICE_BARGE_IN_START_FRAMES=2`，并主要依赖当前 RMS 和候选峰值判断。门槛缺少持续时间、平均能量和脉冲噪声形态约束，因此关门声、碰撞声等尖峰噪声可能满足打断条件。

## 修改方案

- 播放期抢话确认改为至少 4 帧、约 120ms 的持续候选。
- 候选增加平均 RMS 统计，要求平均能量达到动态阈值比例。
- 增加峰值/平均值比例约束，拒绝典型瞬时脉冲噪声。
- `voiceTurnPolicy.canBargeIn()` 保持旧调用兼容，同时支持 `durationMs`、`avgRms`、`maxPeakToAverage` 等播放期防噪参数。
- 拒绝日志新增 `reason`、`avgRms`、`durationMs`、`peakToAverage`，方便现场排查。

## 影响

仅影响数字人播放期间的抢话判定。普通待机监听 VAD 灵敏度不变，真实用户持续说话仍可打断正在播放的回答。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `npm test`（avatar）
