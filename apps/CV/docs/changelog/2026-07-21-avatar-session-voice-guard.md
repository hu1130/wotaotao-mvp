# 2026-07-21 数字人设备会话失效时停止语音假监听

## 问题

租户数字人人设生成后，前台页面出现只显示 `我在听呢`，但语音不再识别、也没有后续回答的情况。日志显示 `computer-mine` 数字人客户端断开后，重新注册成了 `tenant=default`；同时语音轮次出现过 `voice ticket missing` 和 `voice websocket closed before audio sent`。

## 根因

- `/dialog-settings` 在前端失败时会被当作空对象处理，导致页面继续沿用默认租户和默认语音状态。
- 无有效设备会话的前台页面仍会继续连接 avatar WebSocket，从而注册成 `tenant=default` 的活跃数字人。
- `/voice-ticket` 失败时前端只读取成功响应 JSON，409/401 等错误体被吞掉，日志只能看到笼统的 `voice ticket missing`。

## 修改

- `/dialog-settings` 返回 `avatarSessionValid: true` 并设置 `Cache-Control: no-store`。
- 前端统一解析 JSON 错误响应；`/dialog-settings` 401/403/异常时立即关闭语音层，禁用语音按钮，并提示 `设备会话失效，请从客户端重新打开前台`。
- 没有有效设备会话时不再启动麦克风监听、不再开始语音轮次，也不再连接 avatar WebSocket 注册默认租户。
- `/voice-ticket` 失败时记录 HTTP status、reason 和错误 payload，并在界面显示真实认证失败原因。
- 控制台状态同步增加 `avatarSessionValid`、`voiceTenantId`、`voiceDeviceId`，便于排查前台是否绑定到正确租户设备。

## 验证

```powershell
node --check server_deploy/avatar/avatar.js
node --check server_deploy/avatar/server.js
node --test server_deploy/avatar/tests/voice_turn_policy.test.js
node --test server_deploy/avatar/tests/tenant_state.test.js
```

结果：语法检查通过，avatar 语音策略测试 14 条通过，租户状态测试 3 条通过。
