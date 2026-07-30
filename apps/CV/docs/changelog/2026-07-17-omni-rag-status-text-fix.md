# 2026-07-17 Omni RAG 播报状态栏文本修复

## 问题

数字人已经开始播报企业知识库回答时，前端状态栏仍停留在“叮当正在努力思考中”。日志显示外部 RAG 音频已经下发，但服务端 `tts_audio.text` 为空：

```text
Omni 句子开始 ... type=external_rag ... chars=0
Omni 句子下发浏览器 ... type=external_rag chars=0
Omni 语音轮次完成 ... answer_chars=0 source=external_rag
```

这说明问题不在前端渐进展示，而是 `502 external_rag` 链路只返回了音频，没有给浏览器可展示、可入库的最终回答文本。

## 修复方案

企业知识库命中后，不再把最终回答生成交给不可见文本的 `502 external_rag` 事件。服务端改为：

1. 复用 RAG 意图路由命中的知识结果。
2. 通过现有 `DialogChatService` 先生成真实回答文本。
3. 中断 Omni 默认生成，丢弃已缓存的普通回答。
4. 将同一段真实回答文本发送为 `llm_delta`、写入本轮 `_answer_parts`。
5. 使用 `ChatTTSText(500)` 请求 Omni 合成同一段文本。
6. `chat_tts_text` 的 `tts_audio.text` 继续以本次 TTS 请求的 `expected_text` 为唯一真值，保证状态栏字幕、实际播报和最终会话文本同源。

如果回答文本生成前失败，仍释放已缓存的普通回答；如果默认回答已被中断并进入确定性 RAG TTS，则不再回放旧普通回答，避免旧内容污染当前轮次。

## 验证

- `python -m py_compile server_deploy\core\speech_streaming\omni.py`
- 目标单测：
  - `test_external_rag_route_interrupts_default_before_sending_external`
  - `test_external_rag_does_not_play_fixed_wait_cue`
  - `test_external_rag_route_discards_buffered_default_before_send`
  - `test_external_rag_timeout_before_commit_releases_buffered_default`
  - `test_external_rag_without_audio_releases_buffered_default`
  - `test_external_rag_completion_timeout_keeps_committed_answer`
  - `test_chat_tts_ignores_stale_pending_default_text`

本地完整 `test_omni_voice` 文件运行超过 120 秒超时，改用上述本次修复覆盖的目标用例验证。
