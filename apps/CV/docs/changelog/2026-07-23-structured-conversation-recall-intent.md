# 2026-07-23 结构化对话回忆意图

## 问题

用户询问“记得我们昨天聊了啥”一类问题时，ASR 变体或带 filler 的句子可能没有命中确定性对话回忆逻辑，继续进入默认模型，导致回答发散。类似“昨天我们聊了很多”这种疑似回忆但不明确的句子也缺少可控澄清出口。

## 原因

旧实现让 `is_conversation_recall_query()` 返回单个 bool，并依赖完整句式 regex。它不能表达日期、回忆动作、对话动作、目标角色和“不确定但疑似”的中间状态，导致命中失败后绕过人物记忆身份门禁和日期回忆读取链路。

## 修改方案

- 在共享意图路由中新增 `ConversationRecallIntent`，用日期槽、回忆动作槽、对话动作槽、疑问/请求槽解析对话回忆意图。
- 保留 `is_conversation_recall_query()` 作为兼容包装，内部消费结构化解析结果。
- 人物上下文路由改为消费 `ConversationRecallIntent`：确定命中时继续执行身份门禁和历史读取；疑似但不确定时返回澄清，不进入默认模型或 RAG。
- Omni 日期回忆预加载只在确定命中且存在日期 offset 时触发，避免澄清句提前读取个人历史。
- 日志增加 `clarification` 字段，便于区分确定回忆和澄清命中。

## 影响

影响服务端 Omni 语音路由、人物上下文确定性回复和共享意图分类。普通企业知识问题仍按公司词和知识库探测处理；带个人回忆槽的“昨天/刚才聊过什么”会优先走人物上下文。

## 验证

- `python -m py_compile shared_runtime/core/dialog_intent_router.py server_deploy/core/person_sessions/context_intent.py server_deploy/core/speech_streaming/omni.py`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_dialog_intent_router server_deploy.tests.test_person_context_intent -v`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_conversation_recall_uses_session_context server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_yesterday_conversation_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_asr_noisy_yesterday_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_ambiguous_conversation_recall_clarifies_without_memory_or_rag server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_anonymous_yesterday_recall_uses_identity_gate server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_assistant_recall_uses_latest_assistant_context -v`
