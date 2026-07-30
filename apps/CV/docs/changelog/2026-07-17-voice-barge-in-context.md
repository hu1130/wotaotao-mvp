# 2026-07-17 数字人抢话上下文修复方案

## 背景

用户在数字人播报期间插话时，旧播报会被前端停止并向服务端发送 `interrupt`。原链路只上报 `replyId` 和 `playedMs`，服务端会丢弃旧轮次，避免未完整播放的回答进入人物长期记忆。但这也导致下一轮模型缺少“上一轮说到哪里、用户为什么打断”的短期语境，真实对话感不够自然。

## 修复方案

- 前端 `avatar.js` 在抢话和取消当前轮次时，额外上报 `interruption` 上下文：上一轮用户文本、已生成回答、正在播放的句子、播放毫秒数和打断模式。
- 前端同时把被打断轮次写入本地短期 `dialogHistory`，用于无法复用长连接、必须新建 WebSocket 的场景。
- FastAPI 语音 WebSocket 在 `interrupt` 分支解析 `interruption`，并记录上下文字符数、播放进度和打断模式日志。
- Omni 会话在 `interrupt()` 中把被打断内容写入 `_context`，作为下一轮上游模型的短期 `dialog_context`；不设置 `_last_completed_turn`，因此不会提交人物会话或长期记忆。
- 保留原有 `ConversationTruncate(513)` 和下一轮重建上游连接策略，避免旧音频或迟到事件污染新轮次。
- 前端将 `done(reason=interrupted)` 视为旧轮次打断确认，直接丢弃，不再更新 `streamingAudioDone`、清理新轮次 ASR watchdog，也不触发 `playback_complete`，避免旧完成消息污染新轮次。

## 关键不变量

- 被打断回答不进入人物长期记忆。
- 下一轮回答可以利用“上一轮回答被打断、用户听到的部分和正在播放句子”理解补充、否定、纠正或追问。
- 旧轮次的迟到 `done`、音频和 ASR 仍必须通过 `turnId` 隔离。
- 即使旧 `done(interrupted)` 缺少 `turnId`，前端也必须忽略它，抢话清理只由本地 `interruptCurrentVoiceTurnForBargeIn()` / `cancelCurrentVoiceTurn()` 负责。
- 抢话后前端继续优先收用户新语音，数字人旧音频立即停止。

## 验证

- `python -m pytest server_deploy/tests/test_omni_voice.py`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python -m py_compile server_deploy/api/main.py server_deploy/core/speech_streaming/omni.py server_deploy/core/speech_streaming/pipeline.py`
- `node --check server_deploy/avatar/avatar.js`
