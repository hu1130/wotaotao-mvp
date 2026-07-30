# 签退业务时间显式时区

## 问题

`2026-07-22 18:01` 左右，`default` 设备识别到小游重新入场时触发了 repeat，而没有出现 `check_out` 或“远程18点后识别触发签退”日志。现场表现像是 18:00 后签退优先级没有生效。

## 原因

签退窗口此前直接使用 `datetime.now()` 判断本地时间，业务规则隐式依赖容器本地时区。虽然当前服务器 API 容器 `TZ=Asia/Shanghai` 且策略对 `2026-07-22 18:01:57` 会返回签退窗口内，但日志缺少签退判定失败和签退落库失败原因，无法在现场日志里直接区分“业务时间未到”“presence 状态不满足”或“落库未匹配开放记录”。

## 修改方案

- `shared_runtime/core/attendance_policy.py` 增加 `ATTENDANCE_TIMEZONE`，默认 `Asia/Shanghai`，签退窗口按业务时区判断，不再隐式依赖容器本地时区。
- 支持带时区的 `datetime` 入参先转换到业务时区后再判断 18:00 边界。
- 远程识别签退判定未触发时记录业务时区、业务当前时间、签退阈值、窗口结果、presence 和离场时长。
- 签退判定已触发但落库未成功时记录 `reason`，避免继续走 repeat 时没有原因。
- `.env.server.example` 明示 `ATTENDANCE_TIMEZONE=Asia/Shanghai`。

## 影响

影响签到后识别触发签退的业务时间判断和诊断日志。正常上海时区部署行为不变；如果容器系统时区异常，18:00 签退窗口仍按 `Asia/Shanghai` 生效。

## 验证

- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_attendance_policy`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_attendance_policy server_deploy.tests.test_arrival_task_repeat_priority`
- `python -m py_compile shared_runtime/core/attendance_policy.py server_deploy/core/remote_recognition.py`
