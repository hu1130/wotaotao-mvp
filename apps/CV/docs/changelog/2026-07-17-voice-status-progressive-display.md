# 2026-07-17 数字人语音状态栏观感优化方案

## 背景

用户语音识别完成后，前端进入模型思考阶段时会把用户原话拼到状态栏，例如“正在思考：你是谁呀”。这会显得机械，也会让用户误以为数字人在复述问题。播报阶段原策略按句子切换，但每进入一句会一次性显示整句，缺少真人说话时逐步表达的观感。

## 优化方案

- `llm_start` 阶段不再展示用户原话，统一显示“叮当正在努力思考中”。
- `llm_delta` 阶段只累计回答文本，不直接刷新状态栏，避免音频尚未播放时提前暴露整段回答。
- `speechStatusTextAt()` 保留原来的按句子分段策略，但在当前句内部按播放进度逐字展开。
- 新增 `progressiveSegmentText()`，把“当前播放到第几句”和“这一句显示到几个字”拆开，便于测试和后续调参。

## 验证

- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`

