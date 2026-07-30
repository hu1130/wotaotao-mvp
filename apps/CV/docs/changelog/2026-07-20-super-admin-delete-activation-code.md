# 2026-07-20

## 问题

超级管理员客户端详情中可以查看激活码，但不能删除单条激活码。用户需要在激活码条目上右键确认删除。

## 原因

前端详情列表缺少右键交互，Node 网关和 FastAPI 平台管理接口也没有按单个激活码删除的路由。后端只支持删除整个客户端控制面时批量清理激活码。

## 修改方案

- 新增仓储方法按 `tenant_id + activation_id` 删除单条激活码，删除前锁定并校验归属。
- 新增 `ClientAdminService.delete_activation`。
- 新增平台接口 `DELETE /api/v1/platform-admin/clients/{tenant_id}/activations/{activation_id}`。
- 新增 Node 受保护代理 `DELETE /platform-admin/clients/:tenantId/activations/:activationId`。
- 超级管理员激活码条目右键弹出“是否删除该激活码”，确认后删除并刷新列表和详情。

## 影响

只影响超级管理员激活码管理。删除单条激活码不会删除注册机器、管理员账号或业务数据；已被使用的激活码记录也可删除。

## 验证

- 运行 `python -m unittest tests.test_client_admin_service`。
- 运行 Python 编译检查。
- 运行 `node --check` 检查 `server.js` 和 `super-admin.js`。
