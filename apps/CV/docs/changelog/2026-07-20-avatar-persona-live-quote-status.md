# 2026-07-20

## 问题

控制台保存数字人人设后，“数字人人设”右侧的语录生成状态不够实时，用户需要刷新页面才容易看到最终状态。

## 原因

原实现把人设保存和新人设语录生成绑定在同一个长 HTTP 请求里。前端只有请求开始和请求结束两个时刻能更新状态，缺少独立的租户级生成状态通道。

## 修改方案

- API 保存人设后立即记录租户语录生成状态，并通过后台任务生成新人设语录。
- API 新增 `GET /api/v1/tenant-admin/avatar-persona/quote-status` 返回当前租户的生成中、成功、失败或默认状态。
- Node 控制台代理新增 `GET /tenant/avatar-persona/quote-status`。
- 控制台保存人设后立即轮询语录生成状态，右侧实时显示“正在为数字人生成新人设语录”“新语录生成成功”等状态。
- 连续保存时用 `generationId` 避免旧生成任务覆盖新任务状态。

## 影响

影响租户控制台数字人人设保存后的状态展示和语录生成调度。人设保存本身仍同步完成，语录生成改为后台任务。

## 验证

- `python -m py_compile server_deploy/api/tenant_admin.py`
- `node --check server_deploy/avatar/server.js`
- `node --check server_deploy/avatar/control.js`
- `python -m unittest server_deploy.tests.test_tenant_avatar_persona`
- `python scripts/check-runtime-boundaries.py`
