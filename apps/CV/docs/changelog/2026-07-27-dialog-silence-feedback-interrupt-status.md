# 静音反馈被打断后立即恢复静音状态

## 问题

用户说“别说话了”后，系统正确进入业务静音并播放静音反馈语音；如果这段反馈语音被用户打断，状态栏没有立即显示“静音中...”。只有用户在静音状态下再次说话，后端再次返回静音态后，状态栏才恢复为“静音中...”。

## 原因

前端在收到 `dialog_silence active=true` 且带有 `responseText` 时，会把 `voiceDialogSilenceFeedbackActive` 置为 true，避免反馈语音播放期间状态栏提前被“静音中...”覆盖。自然播放完成路径会调用 `completeDialogSilenceFeedbackIfPlaybackIdle()` 清理该标记并恢复静音状态。

打断路径不同：用户抢话或取消当前语音时会清空播放队列、停止音频并重置语音层，但没有清理 `voiceDialogSilenceFeedbackActive`。因此静音状态保护逻辑一直认为“静音反馈还在播放”，不会恢复“静音中...”。

## 修改方案

- 新增 `finishDialogSilenceFeedback()`，统一结束静音反馈播放态并恢复静音状态。
- 自然播放完成、抢话打断、强制重置语音层三条路径都调用该函数。
- 保持普通语音轮次、TTS 队列、后端静音/唤醒判断不变。

## 影响

影响 avatar 前端业务静音状态栏和语音沟通文字的恢复时机。不会改变人脸触发语音、签到语音、业务静音持久状态或唤名解除静音规则。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
