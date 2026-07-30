# 2026-07-20 Omni 空识别快速恢复

## 问题

现场出现数字人停在等待识别/理解状态约 6 秒才恢复。日志显示客户端已停止收音并补静音，但 Omni 没有返回最终识别或服务端判停，且 `partial_chars=0`。

## 原因

旧逻辑把“用户说过话但最终 ASR 未返回”和“噪声/空抢话导致完全没有 ASR 文本”放在同一个 `REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS=6` 窗口内等待。空识别场景没有必要硬等完整 6 秒，用户会感知为卡住。

## 修改方案

- 新增 `REALTIME_DIALOG_EMPTY_ASR_FINAL_TIMEOUT_SECONDS`，默认 2.5 秒。
- Omni 客户端停止收音后，如果仍没有任何 ASR partial 文本，则使用空识别短超时。
- 空识别短超时触发时，回收不确定的上游物理连接，并向浏览器发送 `done(empty_asr)`，不再发送 `asr_final_timeout` 错误。
- 一旦已有 ASR partial 文本，仍使用原 `REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS`，避免正常语音因为网络抖动被过早丢弃。

## 影响

仅影响 Omni 停收音后无任何识别文本的场景。真实说话、RAG、TTS、播放确认和人物记忆提交逻辑不变。

## 验证

- `python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_empty_asr_stop_recovers_before_full_asr_timeout`
- `python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_client_stop_times_out_before_rag_budget_when_asr_never_ends`
