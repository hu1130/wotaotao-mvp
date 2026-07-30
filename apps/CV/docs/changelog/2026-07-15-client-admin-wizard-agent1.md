# Agent1 交付：服务器客户端管理向导

## 背景

管理员需要一个简单入口完成新建客户端、生成激活码、生成或重置控制台密码、删除客户端设备控制面数据、设备启停等操作。按用户要求，本次不做 EXE 打包。

## 改动文件

- `server_deploy/tools/client_admin_wizard.py`
  - 新增交互式菜单脚本。
  - 复用 `TenantAdminRepository`、`DeviceIdentityRepository`、Redis 会话清理能力。
  - 危险清理要求输入完整 `tenant_id`。
- `docs/superpowers/specs/2026-07-15-client-admin-wizard-design.md`
  - 记录功能边界和非目标。
- `docs/superpowers/plans/2026-07-15-client-admin-wizard.md`
  - 记录实现计划。

## 运行方式

服务器 `/opt/server_deploy` 下执行：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api \
  python tools/client_admin_wizard.py
```

查看帮助：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api \
  python tools/client_admin_wizard.py --help
```

## 菜单能力

- 新建客户端：输入租户 ID、租户名称、管理员用户名、设备标签、激活码有效期，输出控制台密码和一次性激活码。
- 生成设备激活码：为已有租户单独生成一次性激活码。
- 重置控制台密码：为指定租户管理员生成新密码，并使旧会话失效。
- 查看租户设备：列出指定租户的注册设备。
- 停用设备 / 启用设备：修改单设备状态。
- 删除客户端控制面数据：删除该租户激活码、注册设备、设备浏览器会话、语音票据；可同时停用该租户控制台管理员。
- 查看租户控制台管理员：列出租户管理员账号状态。

## 删除边界

删除客户端控制面数据不会删除：

- 员工
- 考勤
- 人脸向量
- 知识库
- 人物记忆

脚本输出中的 `businessDataDeleted` 应为 `false`。

## 建议测试

1. 运行 `python tools/client_admin_wizard.py --help`，确认帮助可显示。
2. 用测试租户执行“新建客户端”，确认输出包含控制台密码和激活码。
3. 执行“查看租户控制台管理员”，确认新账号存在且为 active。
4. 执行“生成设备激活码”，确认新增激活码未领取。
5. 执行“重置控制台密码”，确认输出 `sessionsInvalidated: true`。
6. 对测试租户执行“删除客户端控制面数据”，确认需要完整 tenant_id，输出只清理设备控制面数据。
7. 删除后用 `tools/device_admin.py list-devices --tenant-id <tenant>` 和 `list-activations` 复查为空。

## 注意事项

- 生成的控制台密码和激活码只在当前终端输出，不写入文件。
- 如果“新建客户端”时管理员已存在，脚本会询问是否重置密码；选择否时只生成新激活码。
- Agent1 已按职责提供代码和文档，未进行 EXE 打包。
