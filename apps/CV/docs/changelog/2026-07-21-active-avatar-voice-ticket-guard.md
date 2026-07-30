# 2026-07-21

## 问题

用户询问“平时你都在干嘛”时，现场听感出现回答过程中音色变化，且回答未完整播放完状态就回到待机。

## 原因

线上日志显示同一时间存在两个 avatar 展示端连接：avatar server 持续记录 `Dropped STATE_SYNC from inactive avatar`，随后同一 conversation 在 10:03:58 同时开启两个 Omni 语音轮次。两个轮次都识别到同一句“你平时喜欢干嘛？”，并在 10:04:04 分别下发了 64 字和 48 字两段回答音频。10:04:14 只提交了其中一个 turn 的播放完成，10:04:16 两条连接断开，active avatar 变为 none。

音色变化的直接证据是 API 日志出现 `租户克隆音色配置不可用，使用租户默认音色`，随后 Omni 会话以 `clone=False` 的默认音色启动；双语音轮次并发会进一步放大这种听感差异。

## 修改方案

- avatar 前端注册 WebSocket 时使用稳定的页面 `clientId`。
- `/voice-ticket` 请求携带 `X-Avatar-Client-Id`。
- avatar server 在签发语音票据前校验当前租户 active avatar：如果请求来自 inactive/旧展示页，直接返回 409，不允许其开启语音流。
- 更新数字人页和漩涡页脚本版本，确保浏览器加载新的票据校验逻辑。

## 影响

只影响浏览器实时语音入口，防止多个展示页同时抢同一句用户语音。签到、签退、repeat、arrival_task 固定话术的播放优先级不变。音色配置本身未在本次修改中更改；若租户克隆音色继续不可用，仍会按现有策略使用默认音色。

## 验证

- 已运行 `node --check server_deploy/avatar/avatar.js`
- 已运行 `node --check server_deploy/avatar/server.js`
- 已运行 `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- 已通过 `tenant_voice_admin.py resolve --tenant-id computer-mine` 确认当前 effective voice 来自 `platform-shared`，且 `cloneEnabled=false`。
- 已同步到服务器并重建 `avatar` 容器，健康接口 `/healthz`、`/health` 正常，容器内 `node --check avatar.js`、`node --check server.js` 通过。
