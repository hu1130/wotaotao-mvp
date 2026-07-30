# 主动注视话术触发频率优化

## 问题

已签到员工和陌生人持续出现在摄像头范围内时，`checked_in_stare`、`stranger_stare` 主动话术主要依赖上次触发时间做冷却。冷却结束后，同一次在场仍可能再次触发，部分短暂离场路径还会沿用旧的进入时间，导致主动提醒显得重复和机械。

## 原因

识别在场状态只记录了 `last_stare_at`，没有记录“本次入场是否已经触发过主动注视话术”。离场时也没有统一清空注视计时和触发状态，因此重新入场、短暂消失、多人员并存时的行为不够清晰。

## 修改方案

- 为已签到员工和陌生人在场状态增加 `stare_triggered`，同一次在场只允许触发一次主动注视话术。
- 保留 `CHECKED_IN_STARE_TRIGGER_SECONDS=20` 和 `STRANGER_STARE_TRIGGER_SECONDS=20` 的连续注视门槛。
- 保留 `CHECKED_IN_STARE_COOLDOWN_SECONDS=60` 和 `STRANGER_STARE_COOLDOWN_SECONDS=60` 的个人冷却保护。
- 人员离开检测范围后清空当前注视状态，重新进入后必须重新连续停留超过 20 秒才会再次触发。
- 不同员工姓名、不同陌生人 presence key 分别维护状态，互不影响。
- 共享识别流水线中陌生人注视话术只对 `visitor:<id>` 这类已记录陌生人库对象触发。

## 影响

影响人脸识别触发的低优先级主动话术 `checked_in_stare`、`stranger_stare`。签到、签退、首次欢迎、重复签到、实时语音沟通和语音仲裁优先级不变。

服务端 API-only 识别当前仍以 `track:<id>` 维护陌生人在场 key，本次不引入陌生人库迁移，只优化其独立状态和重复频率。

线上 `.env.server` 曾覆盖为 `CHECKED_IN_STARE_TRIGGER_SECONDS=5`、`CHECKED_IN_STARE_COOLDOWN_SECONDS=10`、`STRANGER_STARE_TRIGGER_SECONDS=5`、`STRANGER_STARE_COOLDOWN_SECONDS=10`。本次已调整为 20 秒触发、60 秒冷却；`.env.server` 本身不纳入 Git。

## 验证

- 新增服务端单测覆盖：已签到员工 20 秒后触发一次、同次在场不重复、离场后重新计时、陌生人多人独立触发。
- 新增共享流水线单测覆盖：已签到员工同次在场只触发一次、离场重置、已记录陌生人库触发、临时 track 陌生人不触发。
- 服务器容器内配置验证：`20.0 60.0 20.0 60.0`。
