# 签退优先于在场 repeat/stare

## 问题

临时把签退窗口改为 09:00 后，`computer-mine` 设备上小游当天首次出现会正常签到；重启客户端后，小游再次出现触发了 repeat 和 `checked_in_stare`，没有触发签退。

## 原因

远程识别主分支中已经有“已签到人员先判断签退，再处理 repeat”的逻辑，但帧处理末尾还有一段统一在场维护逻辑：只要 Redis 判断该人员今天已签到，就直接调用 `_handle_checked_in_presence()`。这段逻辑负责 repeat 和 stare，但此前没有先走签退仲裁，因此会绕过主分支的签退优先级。

## 修改方案

- 在统一在场维护入口调用 `_checkout_checked_in_presence_if_due()`。
- 如果签退成功，更新当前帧 label 为“已签退”，并跳过 repeat/stare。
- 将签退判定和签退落库日志收敛为共享 helper，主识别分支和在场维护分支复用同一套逻辑。
- 增加测试覆盖“签退到期时抑制 repeat 重入”。

## 影响

影响已签到人员再次进入画面时的识别后置维护流程。签退窗口内会优先签退；签退窗口外仍按原逻辑触发 repeat、到场任务或 stare。

## 验证

- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_arrival_task_repeat_priority`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_attendance_policy server_deploy.tests.test_arrival_task_repeat_priority`
- `python -m py_compile server_deploy/core/remote_recognition.py`
