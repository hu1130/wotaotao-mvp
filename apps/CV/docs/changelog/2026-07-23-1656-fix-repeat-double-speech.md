# 2026-07-23

## 问题

`repeat` 固定语音触发后会连续播报两次。服务器日志显示同一次 repeat 只调度了一次固定语音，但 avatar 侧同一个 `speech:repeat:<name>` 会启动多次 TTS。

## 原因

Node avatar 网关维护了每个租户最新注册的 active avatar client，但 `/event` 广播仍然发给同租户的所有 avatar WebSocket。客户端重启或页面残留时，旧 avatar 页面仍保持连接，同一条固定语音事件会被多个 avatar 页面各自播放，表现为连续重复播报。

## 修改方案

- `/event` 广播改为只把会播放语音/动作的事件发给 active avatar client。
- 控制台 role 仍继续接收广播，保证状态观察不受影响。
- 增加 `shouldDeliverBroadcastToRole` 策略函数和单元测试，防止广播再次退回“所有 avatar 页面都收到事件”。

## 影响

影响 avatar WebSocket 事件分发。修复 repeat 连播，也避免签到、签退、stare 等固定语音在多个 avatar 页面残留时重复播放。不改变 repeat 触发冷却、识别逻辑或 TTS 文案。

## 验证

- `node --check server_deploy/avatar/server.js`
- `node --check server_deploy/avatar/tenant_state.js`
- `node --test server_deploy/avatar/tests/tenant_state.test.js`
