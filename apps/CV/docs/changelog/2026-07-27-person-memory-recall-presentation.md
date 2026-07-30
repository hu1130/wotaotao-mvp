# 2026-07-27 人物记忆回忆话术改为面向本人表达

## 问题

用户询问“刚才/昨天聊了什么”时，人物记忆回忆可能直接输出内部材料：

- 短期会话回忆按“你说...我回...”复述原始轮次，像在背聊天日志。
- 日期回忆直接念 daily summary，历史摘要里如果包含“用户聊了...”会暴露第三人称 agent 总结。
- 人物记忆 prompt 注入 daily summary 时也可能带入“用户...”这类内部叙述，影响后续模型回答口吻。

## 原因

`PersonContextIntentRouter` 在命中对话回忆后由服务端确定性拼接回答，没有再经过自然话术整理：

- 当前会话分支直接引用原始 `user/assistant` 轮次。
- 日期回忆优先使用 daily summary 原文。
- daily summary 生成 prompt 没有限制“第三人称日志腔”。

## 修改方案

- 新增人物记忆展示层辅助函数，将内部 summary 清洗为面向用户的主题短语。
- 当前会话回忆改为“我们主要聊到...”/“我刚才回答的大意是...”的第一人称自然表达。
- 日期回忆 fallback 不再拼接“你说/我回”，只列主题。
- 人物记忆上下文注入前清洗 daily summary，避免把“用户聊了...”继续喂给模型。
- daily summary 生成 prompt 增加要求：不要生成“用户聊了...”或“用户说/助手说”的流水账。

## 影响

影响人物身份已验证后的个人对话回忆和人物记忆上下文展示。不会改变记忆读取权限、身份校验、RAG 路由或底层历史数据。

## 验证

- `python -m unittest server_deploy.tests.test_person_context_intent server_deploy.tests.test_person_memory server_deploy.tests.test_dialog_intent_router server_deploy.tests.test_person_memory_commands -v`
- `python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_verified_conversation_recall_uses_session_context server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_yesterday_conversation_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_asr_noisy_yesterday_recall_uses_dated_person_memory server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_ambiguous_conversation_recall_clarifies_without_memory_or_rag -v`
- `python -m py_compile ...`
- `python scripts/check-runtime-boundaries.py`
