# 2026-07-22

## 问题

实时沟通中，用户在数字人说话时打断，如果新插话为空或未识别到内容，系统会恢复上一段回答。此时底部状态栏会先显示“刚才我接着说，...”，但音频需要再等 1-2 秒才播放。

## 原因

空插话恢复链路调用 `playRawTTS()` 播放拼接后的继续回答。旧实现会在请求 `/tts-raw` 前立即把 `statusText` 写入 `showStatus()` 和 `updateVoiceChatText()`，但音频需要等待服务端 TTS 合成、浏览器创建音频对象并触发 `playing` 事件。状态栏因此早于真实播放。

## 修改方案

- `playRawTTS()` 默认先显示中性“正在准备语音”，不提前显示将要朗读的文本。
- 浏览器收到音频并进入 `playing` 后，才同步写入朗读文本、底部状态栏和 assistant 文本。
- 空插话恢复分支从提前 `speaking` 改为 `understanding/preparing`，并显示“正在准备继续播放/回答”。
- 增加 `raw tts request started` 和 `raw tts playback started.prepareMs` 日志，便于定位 TTS 准备耗时。

2026-07-22 后续体验优化：移除“正在准备语音/正在准备继续播放/正在准备继续回答”占位文案。TTS 等待期间保持语音状态区域为空，仍然只在浏览器音频进入 `playing` 后显示真实朗读文本。

## 影响

影响所有 `playRawTTS()` 播放路径的底部朗读文本时机。不会改变语音仲裁、播放锁、抢话、TTS 生成和人物记忆提交规则。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `python scripts/check-runtime-boundaries.py`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_voice_clone_tools shared_runtime.tests.test_fixed_tts_voice`
