# 2026-07-17 语音长连接归属释放延迟到轮次完成

## 问题

用户抢话后，新一轮语音已经正确识别并进入回答生成，但前端状态栏一直停在“叮当正在认真思考中”。服务器日志显示：

```text
Omni 服务端判停 ... text=介绍你们的产品。
Omni RAG 文本回答生成完成 ... answer_chars=79
Omni 发送确定性 RAG 文本 TTS ...
Omni 句子开始 ... type=chat_tts_text chars=79
人物会话归属已结束，释放语音长连接 ... current=(none)
语音流连接关闭 ...
```

也就是服务端已经开始 TTS，但人物会话状态检查在音频下发前关闭了 WebSocket，浏览器收不到 `tts_audio` 和 `done`，因此 UI 保持思考态。

## 修复方案

语音 WebSocket 的人物会话释放检查改为：

1. 如果当前没有打开的语音轮次，按原逻辑发送 `session_end` 并关闭长连接。
2. 如果当前 `turn_open=true`，只记录待释放原因，例如 `owner_changed` 或 `suspended_idle`，不立即关闭 WebSocket。
3. 当前轮次收到前端 `playback_complete` 并执行 `finalize_turn_state()` 后，再发送 `session_end` 关闭长连接。

这样人物会话归属变化不会继续保留长连接，但也不会截断已经开始的回答音频和完成信号。

## 验证

- `python -m py_compile server_deploy\api\main.py`

部署后需要关注日志：

- 命中时应出现 `人物会话释放已延迟到当前语音轮次完成`
- 本轮仍应继续出现 `Omni 句子下发浏览器`、`Omni 语音轮次完成`
- 前端播放确认后再出现 `人物会话待释放语音长连接在轮次完成后关闭`
