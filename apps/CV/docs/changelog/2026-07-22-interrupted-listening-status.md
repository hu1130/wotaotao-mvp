# 2026-07-22

## 问题

数字人回答或固定语录说到一半被用户打断后，会停止播放并进入新的监听轮次。但状态栏会被 `startVoiceTurn()` 清空，用户只看到数字人突然不说了，不知道它是在让出话筒听用户说话。

## 原因

之前为了避免环境声触发普通监听时状态栏闪烁，`startVoiceTurn()` 在进入 listening 后统一调用 `clearStatusBeforeDeferredSpeech()`。这个策略适合普通空闲监听，但不适合从正在播报被抢话进入监听的路径。

## 修改方案

- 新增打断监听态文案 `你说，我听着`。
- `startVoiceTurn()` 在检测到实时回答抢话或可打断固定语录被抢话时，状态栏和语音文本显示该文案。
- 普通空闲监听仍保持原有清空状态栏策略，避免环境声造成状态栏闪烁。
- `voice turn start` 日志增加 `interruptedSpeechStatus`，便于确认该轮是否来自播报被打断。

## 影响

只影响数字人正在播报时被用户打断后的前端状态展示，不改变抢话阈值、ASR、LLM、TTS、固定语录是否恢复等业务逻辑。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python scripts/check-runtime-boundaries.py`
