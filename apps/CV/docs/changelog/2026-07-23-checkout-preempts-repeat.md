# 签退语音抢占 repeat 修复

## 问题

18:00 后已签到人员触发签退时，如果 avatar 端已经开始播放 repeat 固定语音，签退语音可能没有播出，现场表现为签退动作被 repeat 话术覆盖。

## 原因

后端和前端都已经配置 `check_out` 优先级高于 `repeat`，但 avatar 的语音抢占逻辑只在不同 owner 之间生效。repeat 和 check_out 都走 `legacy_tts` 固定语音 owner；当 repeat 已进入流式 TTS 播放后，后到的 check_out 虽然优先级更高，却不会停止旧的 WebAudio 流，导致签退语音无法可靠接管。

## 修改方案

- 将语音抢占判断抽到 `voice_turn_policy.js`，明确支持同一 `legacy_tts` owner 内按更高优先级抢占。
- `avatar.js` 在抢占时记录 `preempt speech turn by priority` 日志，并调用现有 `stopCurrentAudio()` 取消旧音频、释放锁和语音优先级。
- 更新 avatar 页面脚本版本号，避免浏览器继续使用旧缓存。

## 影响

影响固定语音播放仲裁。`check_out`、`check_in` 等高优先级固定语音可以抢占正在播放的低优先级 repeat；同优先级、低优先级和 `force=false` 请求不抢占。实时语音优先级和低优先级 stare/crowd 规则不变。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
