# 2026-07-17 数字人回答状态文本回填修复方案

## 背景

状态栏播报阶段偶发一直显示“正在回答”，没有展示回答文本。原因是前端只依赖 `tts_audio.text` 初始化当前音频项文本；当 Omni 音频事件先到、文本通过后续 `llm_delta` / `llm_end` 到达，或 `tts_audio.text` 为空时，播放进度函数拿不到文本，只能显示默认“正在回答”。

## 修复方案

- 新增 `hydrateStreamingAudioText()`，在收到 `llm_delta` 和 `llm_end` 时把回答文本回填到正在播放或排队但文本为空的音频项。
- 当前音频项被回填后立即调用播放状态刷新函数，状态栏按当前播放进度展示文本。
- 播放开始时如果仍无文本，暂时显示“叮当正在努力思考中”，避免退回“正在回答”。
- 保留逐字渐进展示策略，文本到达后继续按音频进度展开。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`

