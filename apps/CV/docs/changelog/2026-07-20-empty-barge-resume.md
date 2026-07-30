# Empty Barge-In Resume

## 背景

数字人回答播放期间，环境噪音或回声可能触发前端 VAD，前端进入“我在听呢”并打断当前回答；如果后续 ASR 没有识别出任何文字，旧逻辑只恢复待机，导致回答被截断。

## 变更

- 前端在播放中的 barge-in 真正清空音频队列前，缓存当前正在播放的回答文本和后续待播文本。
- 如果打断后的语音轮次以 `empty_asr` 结束，说明没有有效用户插话，数字人会用 raw TTS 补播“刚才我接着说，...”后的缓存回答。
- 如果收到 `asr_partial` 或 `asr_final` 且文本包含有效字母/数字/中文等内容，立即清除补播缓存，真实插话仍走原来的大模型回答链路。
- 手动取消、异常重置、切换等 `forceResetVoiceLayer` 场景会清除补播缓存，避免旧回答误补。

## 2026-07-20 追补

- 非持久语音连接下，播放中被 VAD 打断会走 `cancelCurrentVoiceTurn()`，现在该路径也会在清空音频前缓存未说完的回答。
- 当当前轮次是“空打断补播候选”且尚未出现有效 ASR 文本时，客户端 VAD 判停静音窗口缩短到 1.2 秒，避免咳嗽后长时间停在“我在听呢”。
- 线上日志显示咳嗽打断后有时不是返回 `empty_asr`，而是等待 ASR 最终结果直到 watchdog 超时；该超时分支原来会清空补播缓存。现在空打断候选轮次的 ASR 最终结果 watchdog 缩短到 2.5 秒，并在仍无有效文本时直接续播被打断回答。
- 补播回答结束后不再继续显示“播放完成”或“我在听，你直接说话”，而是随播放完成立即清空状态栏，避免字幕残留几秒。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `npm test` in `server_deploy/avatar`

## 观察日志

- `empty barge resume captured`
- `empty barge resumes interrupted speech`
- `empty barge resume cleared`
