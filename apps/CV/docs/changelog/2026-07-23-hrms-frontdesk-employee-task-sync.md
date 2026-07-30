# 2026-07-23 HRMS 智慧前台员工与录脸任务同步

## 问题

上一版只实现了数字人考勤记录回传 HRMS，没有实现 HRMS 员工资料和前台录脸任务主动下发到数字人系统。这样会导致 HRMS 录人后数字人本地员工库没有对应员工，后续人脸识别和考勤同步缺少前置数据。

## 原因

智慧前台云端协议本身是双向业务闭环：

- HRMS 是员工档案和录脸任务的来源。
- 数字人系统负责本地员工表、客户端摄像头录脸、人脸向量库和考勤事件。
- 考勤结果再由数字人系统回传 HRMS。

仅实现考勤回传会让数据流缺少 HRMS -> 数字人的员工同步和任务消费阶段。

## 修改方案

- 扩展 HRMS 前台同步后台线程：
  - 定期拉取 `/api/cloud/frontdesk/employees`，将 HRMS 员工写入数字人员工表。
  - 轮询 `/api/cloud/frontdesk/tasks`，把 `face.captureEnroll` 转成本系统 `capture_face_enroll` 客户端任务。
  - 成功或失败后回传 `/api/cloud/frontdesk/employee-sync-result` 和 `/api/cloud/frontdesk/face/enroll-result`。
- 客户端任务完成时，如果任务带 HRMS 元数据，服务端会回传录脸结果；回传失败会记录日志并允许后续轮询重试该 HRMS 任务。
- 客户端录脸工具支持从任务 payload 接收 `cameraIndex`，避免 HRMS 指定摄像头后客户端仍使用默认摄像头。
- 新增环境变量：
  - `HRMS_FRONTDESK_EMPLOYEE_SYNC_ENABLED`
  - `HRMS_FRONTDESK_EMPLOYEE_SYNC_INTERVAL_SECONDS`
  - `HRMS_FRONTDESK_TASK_POLL_SECONDS`
  - `HRMS_FRONTDESK_TASK_TARGET_DEVICE_ID`

## 影响

- 启用后，HRMS 中的在职员工会自动进入数字人员工表。
- HRMS 页面点击“前台摄像头录入”后，数字人客户端会通过既有客户端任务队列打开录脸窗口并写入向量库。
- 考勤同步仍沿用 outbox 机制，不会因为 HRMS 临时不可用而丢失本地打卡记录。
- 默认配置仍关闭，需要在服务器 `.env.server` 显式启用。

## 验证

- 新增单测覆盖 HRMS 员工同步和录脸任务转客户端任务。
- 需要在部署后验证 API 健康、HRMS 签名接口、服务日志中的员工同步和任务轮询记录。
