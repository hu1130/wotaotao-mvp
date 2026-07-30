# 2026-07-23

## 问题

用户在数字人“空打断恢复回答”播放期间再次打断，下一轮回答语音可以正常播放，但 Live2D 嘴巴不动。

## 原因

恢复回答使用本地 `playRawTTS()` 播放。二次打断后，新一轮实时回答已经开始播放并启动 lip-sync，但旧恢复回答的超时或播放结束 cleanup 仍可能稍后执行，并无条件调用 `stopLipSync()`。这会把新回答的嘴部动画停掉，而不会停止新音频，所以表现为“有声音但嘴不动”。

同类风险也存在于旧 streaming audio chunk 或固定语音播放回调：旧音频回调可能晚于新音频到达，误清理全局 `audio` 或 lip-sync 状态。

## 修改方案

1. 为 lip-sync 增加会话 token、当前音频元素和模式记录。
2. `animateLipByAudio()`、fallback lip-sync、external lip-sync 的旧 RAF 回调只能退出，不能停止新会话。
3. 非流式 `playRawTTS()` cleanup 只有在 lip-sync 仍绑定当前 `playbackAudio` 时才停止嘴部动画。
4. streaming audio chunk 使用闭包内的 `playbackAudio` 做 cleanup，旧 chunk 只能清理自己的音频和 lip-sync。
5. 固定流式 TTS 记录 external lip-sync token，cleanup 只停止自己启动的 external lip-sync。

## 影响

影响 avatar 前端嘴部动画状态管理，不改变 TTS、ASR、LLM、固定语音优先级和 active avatar 广播逻辑。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/*.test.js`
- `python scripts/check-runtime-boundaries.py`
