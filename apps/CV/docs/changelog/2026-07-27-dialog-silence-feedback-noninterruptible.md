# 静音确认反馈不可被抢话打断

## 问题

用户说“别说话了”触发业务静音后，数字人会播放确认反馈，例如“好的，我先不说话了”。这段反馈属于静音控制结果，但此前仍按普通实时回答参与 VAD 抢话仲裁，用户继续说话时可能被打断。

## 原因

avatar 前端已有 `voiceDialogSilenceFeedbackActive` 标记，用于区分静音确认反馈和静音后的“静音中...”状态，但 VAD 抢话入口和 `startVoiceTurn()` 没有检查该标记。只要检测到用户说话，前端仍会创建新语音轮次并取消当前播放。

## 修改方案

- 新增 `isDialogSilenceFeedbackProtected()`，明确静音确认反馈属于不可抢话播放态。
- VAD 监控在该状态下只更新噪声底并重置候选，不进入 barge-in。
- `startVoiceTurn()` 增加二次保护，避免其它入口误取消静音确认反馈。
- 增加前端日志，记录静音反馈期间被忽略的 VAD 和被阻止的新语音轮次。

## 影响

影响 avatar 前端实时语音抢话仲裁。静音确认反馈会完整播放；反馈播放完成后仍恢复为业务静音状态，后续普通说话继续按静音规则忽略，喊数字人名字仍可解除静音。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
