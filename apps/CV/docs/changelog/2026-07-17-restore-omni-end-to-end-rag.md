# 2026-07-17 恢复 Omni 端到端 RAG 修复方案

## 问题

为了解决外部 RAG 音频缺少文本导致前端状态栏停留在“思考中”的问题，上一版把知识库命中后的主回答链路改成了服务端 `DialogChatService` 先生成答案，再通过 `ChatTTSText(500)` 让 Omni 合成音频。

这会把原本的端到端语音模型回答降级成“服务端预生成文本 + TTS”，导致同一个问题的回答风格、上下文连贯性和自然程度发生变化。

## 修复方案

1. 删除 `OmniVoicePipelineSession._build_external_rag_answer_text()`，主链路不再调用服务端 chat completion 代替 Omni 回答。
2. 知识库命中后继续构建官方 `external_rag` payload，并恢复通过 `send_external_rag()` 发送 `ChatRAGText(502)`。
3. 保留串行安全约束：发送 502 前等待默认 TTS 通道结束，避免上游默认回答占用 TTS 通道时静默吞掉外部 RAG。
4. 不重新引入固定等待话术，保持 2026-07-15 已确定的“无 RAG 固定等待语”体验。
5. 默认回答仍暂存到外部 RAG 首段音频提交为止：首段提交后丢弃默认回答；首段超时或 502 完成但没有外部音频时，释放一次默认回答。
6. 前端播放音频但暂时没有文本时，状态栏显示说话态，不再停留在“努力思考中”。真正的回答文本仍只来自后端 `llm_delta` 或 `tts_audio.text`。

## 验证

- `python -m py_compile server_deploy\core\speech_streaming\omni.py server_deploy\core\speech_streaming\tts_expectation.py`
- `node --check server_deploy\avatar\avatar.js`
- `git diff --check`
- `PYTHONPATH=. python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_route_sends_502_after_default_settles tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_502_is_not_prefilled_by_server_answer tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_commit_discards_buffered_default`
- `PYTHONPATH=. python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_timeout_before_commit_releases_buffered_default tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_completed_without_audio_releases_buffered_default tests.test_omni_voice.OmniVoicePipelineSessionTests.test_external_rag_completion_timeout_keeps_committed_answer`
- `PYTHONPATH=. python -m unittest -v tests.test_tts_expectation`

说明：系统 Python 未安装 `pytest`，本次使用测试文件自身的 `unittest` 入口完成验证。
