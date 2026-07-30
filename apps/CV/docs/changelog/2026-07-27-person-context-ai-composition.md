# 2026-07-27 人物身份和记忆回答改为 AI 组织

## 问题

人物上下文命中后仍然容易出现固定句式：

- 每次问“你知道我是谁吗”都回答“当然认识，你是...”，缺少上下文变化。
- 记忆/回忆类问题常以“记得...”开头，并把服务端拼好的主题句直接念出来。
- 这类回答虽然来自可信身份和记忆，但没有真正经过最终对话模型按用户问题组织。

## 原因

`PersonContextIntentRouter` 同时承担了“可信事实判断”和“最终话术拼接”：

- 身份问题直接生成固定最终句。
- 回忆问题直接生成 `记得...` 的最终句。
- `omni.py` / `pipeline.py` 再把这段文本作为 `canonical_text` 和 `required_facts` 传给动态话术模型，导致模型被固定句式锚定。

## 修改方案

- `PersonContextReply` 增加 `required_facts`、`response_goal`、`constraints`。
- 人物上下文路由只输出可信事实、回答目标和约束，不再把“知道/记得”类固定句式作为最终答案。
- Omni 和 Cascade 语音链路调用场景话术模型时，将 `canonical_text` 留空，只传可信事实给模型组织表达。
- 身份回答约束为只使用服务端已验证姓名，不使用客户端自报姓名，不声称知道未提供信息。
- 记忆回答约束为贴合用户问法，不逐字背日志，不输出“你说...我回...”，不固定以“记得”开头。

## 影响

影响已验证人物的身份确认、当前对话回忆、日期对话回忆和未验证身份拦截话术。身份校验、记忆读取权限、RAG 路由和底层记忆数据不变。

## 验证

- `python -m unittest server_deploy.tests.test_person_context_intent server_deploy.tests.test_person_memory server_deploy.tests.test_dialog_intent_router server_deploy.tests.test_person_memory_commands -v`
- `python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_person_identity_query_uses_scene_reply server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_conversation_recall_uses_session_context server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_yesterday_conversation_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_asr_noisy_yesterday_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_ambiguous_conversation_recall_clarifies_without_memory_or_rag server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_anonymous_yesterday_recall_uses_identity_gate -v`
- `python -m py_compile ...`
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
