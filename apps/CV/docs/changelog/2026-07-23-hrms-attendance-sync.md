# HRMS 考勤同步

## 问题

数字人前台已经能在本系统 MySQL 中记录员工签到、签退，但当前人事系统不会自动收到这些考勤数据，需要人工查看或额外导入，两个系统之间没有形成实时闭环。

## 原因

HRMS 已提供 `/api/cloud/frontdesk/attendance/push` 云端智慧前台推送接口，并要求 HMAC 签名；数字人项目已有考勤落库、Redis 状态和 avatar 事件，但缺少面向 HRMS 的签名客户端、员工映射和失败重试机制。

## 修改方案

- 新增 `shared_runtime/config/hrms_sync.py`，通过环境变量配置 HRMS URL、API key、secret、设备号、超时和重试间隔。
- 新增 `shared_runtime/core/hrms_attendance_sync.py`：
  - 签名请求 HRMS 云端智慧前台接口。
  - 拉取 HRMS 员工列表，按 `frontdeskNickname/name/employeeNo` 映射 `employeeId`。
  - 生成带 `externalId` 的签到/签退记录，交给 HRMS 去重。
  - 推送失败时保留 MySQL outbox，后台线程定时重试。
- 扩展 `shared_runtime/core/attendance_db.py`，新增 HRMS 同步 outbox 表和待同步记录读写方法。
- 在手动 API 签到/签退、远程识别自动签到/签退、自动签退路径中，考勤落库成功后立即入队并尝试同步 HRMS。
- 更新 `.env.server.example`，新增 HRMS 同步配置模板。

## 影响

启用 `HRMS_ATTENDANCE_SYNC_ENABLED=1` 并配置 HRMS 凭据后，数字人考勤会同步到 HRMS。默认关闭时现有考勤行为不变。

同步失败不会回滚数字人本地考勤记录；失败原因会写日志，并保留 outbox 等待重试，避免因为 HRMS 短暂不可达丢记录。

## 验证

- `python -m py_compile shared_runtime\config\hrms_sync.py shared_runtime\core\hrms_attendance_sync.py shared_runtime\core\attendance_db.py shared_runtime\core\auto_checkout_scheduler.py server_deploy\api\services.py server_deploy\core\remote_recognition.py server_deploy\api\main.py`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_hrms_attendance_sync server_deploy.tests.test_api_services -v`
- `python scripts\check-runtime-boundaries.py`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_attendance_policy server_deploy.tests.test_arrival_task_repeat_priority -v`

## 部署

需要同步 `server_deploy/` 与 `shared_runtime/` 到服务器，配置 `/opt/server_deploy/.env.server` 中的 HRMS 同步变量，重建 API 容器，并检查 API 日志中的 `HRMS 考勤同步` 关键日志。

当前 HRMS 公网同步地址应使用 `https://hrms.setdx.com`；`hrms.shendux.com` 是旧部署脚本中的历史地址，不对应当前 5173 HRMS 实例的云端前台鉴权配置。
