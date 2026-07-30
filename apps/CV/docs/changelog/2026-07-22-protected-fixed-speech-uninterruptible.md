# 2026-07-22

## Protected 固定语音播放期间禁止被 VAD 打断

### 根因

`check_in`、`check_out`、`arrival_task`、`first_time`、`returning`、`repeat`、`stranger`、`returning_stranger` 已经被列为 protected fixed event，可以在噪音造成的空 listening 状态中直接播放。

但前端播放固定语音时，`canUserBargeInFixedSpeech()` 对所有非空 `eventType` 都返回可打断，导致这些 protected 固定语音播放期间仍可能被 VAD 误判的新语音轮次切掉。

### 修改

- 将 protected fixed event 名单收敛到 `voice_turn_policy.js`。
- protected fixed event 仍可打断空 listening，但自己播放期间不可被用户 barge-in/VAD 打断。
- `stranger_stare`、`checked_in_stare`、`idle_long`、`crowd`、`gesture_*` 仍不按 `check_in` 级别保护。
- 更新 avatar 页面脚本版本号，避免浏览器沿用旧的 `voice_turn_policy.js` 缓存。

### Repeat 当前触发阈值

代码默认值：

- `CHECKED_IN_ABSENT_GRACE_SECONDS=2.0`
- `CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS=2.0`
- `REPEAT_FEEDBACK_COOLDOWN_SECONDS=15`

当前服务器 `.env.server` 覆盖：

- `CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS=3`
- `REPEAT_FEEDBACK_COOLDOWN_SECONDS=3`

因此当前线上通常需要已签到人员消失超过约 3 秒，再次出现时触发 `repeat` 或 `arrival_task`；同一人的 `repeat` 触发后还有 3 秒冷却。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
