# 2026-07-23

## 问题

HRMS 智慧前台下发拍照任务准备改为由设备端输入员工姓名，但数字人客户端任务 worker 在任务缺少 `name` 时会直接失败，HRMS 回传同步器也会在缺少 `employeeId` 时跳过结果回传。

## 原因

旧链路默认任务一定来自 HRMS 已选员工，因此强依赖 `employeeId` 和预填 `name`。当任务改成“租户 + 设备 + 设备端输入姓名”后，客户端、shared runtime 回传契约都缺少对应分支。

## 修改方案

- `client_deploy/core/client_task_worker.py`：人脸录入任务缺少姓名时，在设备端弹出姓名输入框，弹窗不可用时再尝试命令行输入；任务结果回传姓名和 `nameSource`。
- `shared_runtime/core/hrms_attendance_sync.py`：允许无 `employeeId` 的人脸录入任务按结果中的姓名继续回传 HRMS，并附带租户、设备、客户端任务 ID 和 HRMS 任务 ID。
- `server_deploy/tests/test_hrms_attendance_sync.py`：增加无 `employeeId` 但有设备端姓名的回传契约测试。

## 影响

影响数字人客户端任务执行和 HRMS 人脸录入结果回传。已有带 `employeeId` 和 `name` 的任务仍保持原行为。

## 验证

- 已执行：`py -m py_compile client_deploy/core/client_task_worker.py shared_runtime/core/hrms_attendance_sync.py`，通过。
- 已执行：`$env:PYTHONPATH='D:\CV_deploy\dist_deploy\shared_runtime;D:\CV_deploy\dist_deploy\server_deploy'; python -m unittest server_deploy.tests.test_hrms_attendance_sync`，6 个测试通过。
- 已执行：`python scripts/check-runtime-boundaries.py`，通过。
- 已执行：`git diff --check -- client_deploy/core/client_task_worker.py shared_runtime/core/hrms_attendance_sync.py server_deploy/tests/test_hrms_attendance_sync.py docs/changelog/2026-07-23-1507-hrms-frontdesk-device-input-task.md`，通过。

## 部署

- 本地提交：`3875e18 修复：HRMS拍照任务支持设备端输入姓名`。
- 已同步 `shared_runtime/core/hrms_attendance_sync.py` 到 `myserver:/opt/shared_runtime/core/`。
- 已同步 `client_deploy/core/client_task_worker.py` 到 `myserver:/opt/client_deploy/core/`，作为客户端部署包源码基线；已运行中的 Windows 客户端仍需要更新/重启到新包后才会弹出设备端姓名输入框。
- 已重建并重启 `myserver` 数字人 API 容器，`/health`、`/healthz` 正常。
- 部署排查发现数字人 `.env.server` 的 HRMS HMAC 凭证与 HRMS 配置不匹配，已备份并对齐；备份已移至 `/opt/server_deploy_env_backups/`，未打印或提交密钥。
- 已在容器内调用 HRMS cloud employees 接口验证 HMAC，返回 `ok=True`，不再 401。
