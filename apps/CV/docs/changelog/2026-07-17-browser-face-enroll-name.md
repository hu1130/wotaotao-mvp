# 浏览器输入人脸录入姓名修复方案

## 背景

语音触发“录人脸”但未识别出员工姓名时，旧链路仍会创建 `capture_face_enroll` 客户端任务，并让 Windows 客户端弹出 tkinter 输入框。这个输入框不在数字人浏览器里，现场交互割裂，也容易被 kiosk/前台窗口遮挡。

## 方案

1. 语音动作未拿到姓名时不再创建客户端任务，而是返回 `input_required`，由数字人浏览器展示姓名输入浮层。
2. 浏览器提交姓名到同源 Node 端 `/avatar/faces/capture`，该接口要求有效 `cv_avatar_session`，前端不接触 HMAC、设备私钥或长期 token。
3. Node 使用 avatar session 透传 `X-Avatar-Session` 到 FastAPI 创建 `/api/v1/client-tasks`，FastAPI 只允许 avatar session 创建 `capture_face_enroll` 任务。
4. FastAPI 将 avatar session 创建的任务强制绑定到当前 `device_id`，禁止浏览器指定其他设备，保证任务可达且租户/设备隔离。
5. Windows 客户端收到空姓名任务时直接失败上报，不再退回本地弹窗。

## 验证重点

- 语音命令无姓名时，浏览器出现输入框而不是本地弹窗。
- 提交后任务 payload 包含 `name`，目标设备等于当前数字人设备。
- avatar session 不能领取任务、完成任务或上传向量，只能创建人脸录入任务。
