# 2026-07-20

## 问题

考勤系统到 18:00 后会由服务端定时线程批量自动签退所有已签到但未签退员工。实际业务需要的是：18:00 后员工人脸再次出现在摄像头前并被识别时，才按当前时间写入签退；如果员工当天尚未签到，即使在 18:00 后首次被识别也应先签到。

## 原因

原实现把 18:00 设计为批量签退任务触发时间，服务端启动时会启动 `AutoCheckoutScheduler`。同时人脸识别状态机遇到“已签到”员工只做重复签到/在场处理，没有在 18:00 后的重新入场识别事件中执行签退。

## 修改方案

- 新增共享考勤策略 `core.attendance_policy`，统一判断签退窗口和“已签到员工是否应在本次识别中签退”。
- 服务端启动不再启动 18:00 批量自动签退线程，避免员工未出现也被写入签退。
- 服务端远程识别、本地共享识别流水线和客户端遗留远程识别服务都改为：已签退则保持去重；已签到且 18:00 后首次出现或离场后重新出现才签退；未签到员工仍走签到分支。
- 缓存命中的已知员工也回流到同一个考勤状态机，避免缓存路径绕过 18:00 后签退判断。
- 本地手动/识别签退在没有当天未签退记录时不再伪造签退事件。

## 影响

影响人脸识别触发的签到/签退状态机和服务端启动任务。历史考勤数据不迁移；已存在的自动签退记录不会被修改。默认签退触发窗口仍为 18:00，可通过 `ATTENDANCE_CHECKOUT_AFTER_HOUR` 和 `ATTENDANCE_CHECKOUT_AFTER_MINUTE` 调整。

## 验证

- `python -m unittest tests.test_attendance_policy tests.test_remote_checkin_store tests.test_api_services`（在 `server_deploy/` 下执行）
- `python -m py_compile shared_runtime/core/attendance_policy.py shared_runtime/core/recognition_pipeline.py server_deploy/core/remote_recognition.py client_deploy/core/remote_recognition.py server_deploy/api/main.py`
- `python scripts/check-runtime-boundaries.py`
