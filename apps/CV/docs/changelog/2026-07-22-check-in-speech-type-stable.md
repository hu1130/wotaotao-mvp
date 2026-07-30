# 签到固定语录统一使用 check_in

## 问题

远程签到成功后，服务端会继续携带 `is_first` / `is_returning` 字段。固定语音分发层此前会把 `check_in + is_returning` 转成 `returning`，把 `check_in + is_first` 转成 `first_time`，导致“签到成功”动作播放的不是 `check_in` 语录。

## 原因

`is_first` / `is_returning` 原本同时承担了动作差异和语录分类两个职责。当前产品规则要求每次签到成功都播放签到语录，因此语音层不应再根据这两个字段改写签到语音类型。

## 修改

- `server_deploy/core/avatar_event_dispatcher.py`：`check_in` 事件固定使用 `check_in` 语音类型。
- `shared_runtime/core/voice_system.py`：同步移除旧链路中的 `check_in` 到 `first_time` / `returning` 的语音映射。
- 保留陌生人 `stranger + is_returning -> returning_stranger` 逻辑。

## 验证

- 覆盖 `is_returning=True` 和 `is_first=True` 两类签到事件，确认 speech payload 的 `event_type` 均为 `check_in`。
