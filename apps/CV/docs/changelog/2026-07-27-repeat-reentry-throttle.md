# Repeat 重新入场触发降频

## 问题

`computer-mine` 日志中 repeat 播报出现频繁触发。用户现场感知为数字人反复欢迎同一个已签到员工，交互显得机械。

## 原因

线上配置为：

- `CHECKED_IN_ABSENT_GRACE_SECONDS=2`
- `CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS=3`
- `REPEAT_FEEDBACK_COOLDOWN_SECONDS=3`

摄像头短暂漏检 5-10 秒时，服务端会把已签到员工标记为离场；下一帧重新识别到同一个人后，因为 absent 超过 3 秒且 repeat 冷却也只有 3 秒，就会再次触发 `repeat`。日志中多次出现 `faces=0`、`远程已签到离场`、`远程已签到重新入场`、`远程 repeat 已触发` 的连续链路。

## 修改方案

- 新增 `CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS`，专门控制 repeat/到场任务重新入场触发阈值。
- 签退判断仍使用 `CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS`，避免为了降低欢迎频率而影响 18 点后识别签退。
- repeat 重新入场默认至少要求离开 20 秒。
- 线上 `computer-mine` 当前调整为：离场确认 8 秒、repeat 重新入场至少离开 60 秒、repeat 播报冷却 60 秒。

## 影响

影响已签到员工重新入场时的 `repeat` 和到场任务触发频率。持续在场注视 20 秒后的 `checked_in_stare`、签退、首次签到和实时沟通不改变。

## 验证

- 新增单测覆盖短暂摄像头漏检不会触发 repeat。
- 服务器日志已确认此前 repeat 来自 `远程已签到重新入场`，不是 avatar 队列重复播放。
