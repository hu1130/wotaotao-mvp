# Aivora 域名展示入口调整

## 问题

`https://aivora.shendux.com` 已经解析到服务器并通过 HTTPS 反代到当前 CV 项目，但 avatar 服务端对 `/`、`/index.html`、`/vortex-runtime.html` 强制要求 `cv_avatar_session` 设备会话。裸域名访问会返回 `avatar device session required`，导致无法作为数字人展示入口直接打开。

## 根因

域名和证书链路已经存在，阻塞点不在 Nginx，而在 avatar 静态页面入口的设备会话保护。该保护适合客户端启动后的完整联动会话，但不适合作为公开展示页面壳子的域名入口。

## 修改

- `server_deploy/avatar/server.js` 新增 `AVATAR_PUBLIC_DISPLAY_ENABLED` 开关，默认启用。
- 默认放行 `/`、`/index.html`、`/vortex-runtime.html` 的页面壳子访问。
- WebSocket、TTS、dialog-settings、控制台、超级管理员和平台管理 API 仍保持原有认证。

## 验证

- `https://aivora.shendux.com` 应返回数字人 HTML 页面。
- `https://aivora.shendux.com/control-login.html` 应返回企业控制台登录页。
- `https://aivora.shendux.com/super-admin.html` 未登录时应跳转或拒绝，登录平台管理员后可进入。
