# 2026-07-27 人物上下文动态话术失败不再无声结束

## 问题

用户询问“我们之前聊过什么”时，前端状态栏结束显示，但数字人没有播报。

## 原因

人物上下文意图命中后，Omni 链路会先中断上游默认回答，再调用 DashScope 对话模型生成自然话术。线上日志显示本轮调用对话模型返回阿里云 `Arrearage` 400，动态话术生成失败。由于默认回答已经被中断且没有缓存音频可释放，轮次以 `answer_chars=0` 完成，用户侧表现为状态栏消失且无语音。

进一步复盘后确认，浏览器 Omni 本身已经有火山端到端模型和 `external_rag` 事件能力。人物身份和对话回忆这类场景只需要服务端提供可信身份、记忆事实和表达约束，最终组织与播报应交给火山 Omni 完成，不应绕到 DashScope 再合成一段固定 TTS 文本。

## 修改方案

- Omni 人物上下文分支不再调用 DashScope `scene_reply()` 组织口播，而是构造“人物上下文” `external_rag` payload，通过火山 502 事件交给 Omni 端到端模型自然回答和播报。
- 人物上下文 502 payload 只包含服务端可信事实、回答目标和表达约束，不混用企业知识检索结果。
- 火山 502 失败、超时或没有提交音频时，先尝试释放已缓存的默认回答；没有可释放内容时，播报明确的“当前无法整理对话”提示，避免空轮次结束。
- Cascade 人物上下文分支同样在动态话术失败时播报可听见的失败提示。
- 线上 `DIALOG_CHAT_MODEL` 从 `qwen3.6-flash-2026-04-16` 切换为 `qwen3.6-plus`，并保持 `DIALOG_CHAT_ENABLE_THINKING=0`。

## 影响

正常身份和记忆回答在 Omni 语音里由火山端到端模型根据可信事实组织，不退回旧的“记得...”硬拼接，也不再受 DashScope 对话模型欠费影响。Cascade 语音仍使用 DashScope 动态话术。

人物记忆提炼、每日总结、embedding 和企业知识 RAG 的 qwen/DashScope 配置未迁移、未改动；这些后台能力等待 qwen 续费后继续使用原链路。

## 验证

- `python -m unittest tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_person_identity_query_uses_external_rag tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_conversation_recall_uses_session_context tests.test_omni_voice.OmniVoicePipelineSessionTests.test_yesterday_conversation_recall_uses_dated_person_memory tests.test_omni_voice.OmniVoicePipelineSessionTests.test_asr_noisy_yesterday_recall_uses_dated_person_memory tests.test_omni_voice.OmniVoicePipelineSessionTests.test_ambiguous_conversation_recall_clarifies_without_memory_or_rag tests.test_omni_voice.OmniVoicePipelineSessionTests.test_anonymous_yesterday_recall_uses_identity_gate tests.test_omni_voice.OmniVoicePipelineSessionTests.test_person_context_external_rag_waits_for_default_without_interrupt tests.test_omni_voice.OmniVoicePipelineSessionTests.test_person_context_external_rag_error_speaks_failure_notice tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_assistant_recall_uses_latest_assistant_context -v`
- `python scripts/check-runtime-boundaries.py`
- 服务器容器内确认 `config_model=qwen3.6-plus`，`payload_enable_thinking=False`。
- 服务器实际模型探针仍返回阿里云 `Arrearage`，说明当前剩余阻断点是 DashScope 账号计费状态，不是模型名或 thinking 开关。
