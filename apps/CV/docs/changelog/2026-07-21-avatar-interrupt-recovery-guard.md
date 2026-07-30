# 2026-07-21 数字人打断恢复与固定语录防噪保护

## 问题

数字人被打断后偶发不再回答，页面一直停在“我在听呢”或监听态。线上日志中能看到用户抢话后连续出现新语音轮次、`voice turn cancelled`，服务端正在路由或准备回答的轮次被再次取消，最终没有回答音频落地。

## 原因

浏览器在服务端 VAD 已经判停、旧轮进入 ASR/路由/LLM/TTS 准备阶段后，会设置 `voiceStopRequested=true`。这时旧逻辑只要检测到 2-3 帧 VAD 起点，就允许 `canInterruptPendingResponse` 取消当前 pending answer。环境噪声、尾音或短促声音会把尚未播出第一个字的回答取消掉；由于此时没有 `assistantText` 或 `replyId`，空抢话恢复缓存也可能被下一次 `cancelCurrentVoiceTurn()` 清掉。

另外，`stranger_stare` 和 `checked_in_stare` 固定语录曾被设为可被用户抢话，播放期间不再完全走固定语录防噪保护，容易再次放大误触发。

## 修改方案

- `canInterruptPendingResponse` 增加可选的强语音证据判断：pending answer 阶段必须满足抢话级别的帧数、持续时长、平均响度和峰值比例，才允许取消旧轮并开启新轮。
- avatar VAD 在思考/准备回答阶段保留候选音频，但未达到强证据前只记录拒绝日志，不再取消旧轮。
- 固定语录恢复为播放期间受防噪保护，不再把 `stranger_stare` / `checked_in_stare` 当作可被普通 VAD 抢话的回答音频。

## 影响

影响数字人和漩涡共用的 avatar 语音前端状态机。真实用户持续插话仍可打断 pending answer；短噪声、固定语录尾音和轻提醒播放声不再把正在准备的回答取消。固定语录仍可打断真正没有用户语音证据的空监听轮次。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`

## 2026-07-21 追补

现场复测发现上一次为了避免误打断，把固定语录播放期间的真人抢话也关闭了；同时实时回答播放时的抢话阈值在现场环境下偏高，用户正常开口会多次落在 `vad barge below threshold`。

本次恢复固定语录“真人说话可打断”的能力：固定语录只要带事件类型，都可以进入统一抢话判定。抢话阈值调整为更贴近现场人声，但仍要求多帧、持续时长、平均响度和峰值比例同时满足，避免短噪声再次取消 pending answer。
