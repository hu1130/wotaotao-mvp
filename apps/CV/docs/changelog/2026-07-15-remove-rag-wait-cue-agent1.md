# Agent1 交付：移除检索前固定反馈

## 背景

当前 Omni 外部 RAG 命中知识库后，会在发送 `ChatRAGText(502)` 前先播放固定等待话术，例如“我帮你查一下，请稍等。”或环境变量中配置的“稍等一下哈，我查查看”。用户要求去掉这种每次检索前的固定反馈。

## 修复方案

- 移除 Omni RAG 串行流程中的 `rag_wait_cue` 阶段。
- 保留官方串行安全约束：仍等待默认 TTS 通道结束后再发送外部 RAG `502`。
- 新流程变为：`default TTSEnded -> external_rag 502`。
- 删除 `_play_rag_wait_cue()`，不再发送 `ChatTTSText(500)` 等待话术。
- 删除 `REALTIME_DIALOG_RAG_WAIT_TEXT` 示例配置，避免管理员继续配置已废弃项。
- 同步删除实际 `.env.server` 中的 `REALTIME_DIALOG_RAG_WAIT_TEXT` 行。

## 改动文件

- `server_deploy/core/speech_streaming/omni.py`
- `server_deploy/config/voice.py`
- `server_deploy/tests/test_omni_voice.py`
- `server_deploy/.env.server.example`
- `server_deploy/.env.server`

## 测试重点

1. 知识库命中后不再调用 `send_chat_tts_text()` 播放固定等待话术。
2. 外部 RAG 仍必须等待默认 TTS 结束后再发送 `502`。
3. 默认通道超时仍不发送 `502`，继续回退普通回答。
4. 外部 RAG 超时/无音频的默认回答回退逻辑不变。

## 验证命令

```bash
python -m unittest server_deploy.tests.test_omni_voice -v
python -m py_compile server_deploy/core/speech_streaming/omni.py server_deploy/config/voice.py
```

服务器同步后在 API 容器内执行：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api \
  python -m unittest tests.test_omni_voice -v
```
