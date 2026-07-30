# 2026-07-20

## 问题

用户在浏览器地址栏访问 `/control-auth/logout` 时返回 `Cannot GET /control-auth/logout`，无法直接退出当前租户管理员会话后切换到超级管理员账号。

## 原因

Node 控制台只提供 POST `/control-auth/logout`，控制台按钮可以正常退出，但没有面向浏览器导航的 GET 入口。

## 修改方案

抽出 `logoutControlSession` 复用云端会话撤销、本地会话缓存清理和 HttpOnly Cookie 清理逻辑。POST 继续返回 JSON，GET 复用相同退出逻辑后重定向到 `/control-login.html`。

## 影响

不改变现有按钮退出流程。新增 GET 仅用于浏览器直接访问退出，不暴露租户切换能力。

## 验证

- 本地执行 `node --check server_deploy/avatar/server.js`。
- 同步服务器后重建并重启 avatar，验证 GET `/control-auth/logout` 返回 302 到登录页。
