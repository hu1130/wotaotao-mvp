# 2026-07-22

## 问题

用户已经在当天签到后，出现在 `default` 摄像头前时触发了 `checked_in_stare`，没有先触发 `repeat`。日志显示服务端识别到 `tenant=default`、`name=小游`，但分支为“远程已签到在场状态初始化”，随后停留超过 stare 阈值触发了 `checked_in_stare`。

## 原因

`RemoteRecognitionService._handle_checked_in_presence()` 只有在已有 presence 状态从 `present=False` 恢复为 `present=True` 时才认为是重新入场。当前设备或进程第一次看到当天已签到人员时，旧逻辑只初始化 presence 并直接返回，不会触发 repeat。这样与业务定义不一致：repeat 应表示“签到后，该人今天再次入场”，也应包含当前摄像头运行域首次建立已签到在场状态的场景。

## 修改方案

- 今天已签到人员在当前运行域首次建立 presence 时，如果 `emit_repeat=True`，按重新入场触发到场任务或 repeat。
- 签到成功路径仍使用 `_mark_checked_in_present()` 预先建立 presence，因此不会把刚签到本人误判为 repeat。
- 轨迹追溯恢复路径继续传 `emit_repeat=False`，只初始化 presence，不触发 repeat。
- 增加测试覆盖首次看到已签到人员触发 repeat，以及轨迹恢复不触发 repeat。

## 影响

影响服务端远程识别的已签到人员入场仲裁。已签到人员首次被某个摄像头运行域看到时会优先触发 repeat/到场任务；持续停留后的 `checked_in_stare` 逻辑不变。

## 验证

- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_arrival_task_repeat_priority`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_arrival_task_speech server_deploy.tests.test_attendance_policy server_deploy.tests.test_arrival_task_repeat_priority`
- `python -m py_compile server_deploy/core/remote_recognition.py`
- `python scripts/check-runtime-boundaries.py`
