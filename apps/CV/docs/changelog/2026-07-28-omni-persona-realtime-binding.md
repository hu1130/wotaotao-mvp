# 2026-07-28

## 问题

控制台保存数字人人设后，普通火山 Omni 实时沟通现场无法确认是否使用了新人设；用户体感上像仍在使用旧默认风格。

后续线上日志确认：实时会话已经带上 `persona_name=小丑` 和 `persona_version=9`，但实际回复仍不稳定地偏离控制台“暴躁、阴阳怪气、愤怒”等人设。

## 原因

Omni 长连接会在每轮开始前比较租户人设版本并按需重建上游物理连接，但旧逻辑只看 `version`，如果运行态出现人工修正、缓存异常或版本号未变化，可能继续复用旧上游会话。就绪日志也只记录音色版本，不记录人设版本、名字或 prompt 指纹，导致线上无法验证 `start_session` 里实际绑定的人设。

实时 `speaking_style` 对自定义人设仍先继承系统默认“温柔活泼、亲切”的语气，再追加租户语气。该默认语气和控制台人设冲突，削弱了火山 Omni 对自定义人设的遵循。

另外，“我问你是谁？”这类助手身份问句包含“我/问/？”槽位，被人物上下文路由误判为对话回忆，进入人物记忆外部 RAG，进一步稀释了“被问你是谁时回答我是当前名字”的人设约束。

## 修改方案

- 将下一轮前的人设变化判断从仅比较 `version` 改为比较完整人设设置。
- Omni 上游就绪日志增加 `persona_version`、`persona_name`、`persona_customized`、prompt 长度和脱敏 hash。
- 增加单测，覆盖普通实时沟通 payload 携带控制台人设，以及人设变化会在下一轮前重建上游连接。
- 自定义租户人设的实时 `speaking_style` 不再继承系统默认亲切语气，改为明确优先控制台人设、语气和补充要求。
- 助手身份问句在没有明确“刚才/上次/记得”等回忆范围时，不再被解析成对话回忆或人物上下文外部 RAG。

## 影响

影响火山 Omni 普通实时沟通长连接、租户人设解析和共享意图路由。不会改变静音/解除静音动态反馈链路，不降低 ASR、LLM、TTS 或 RAG 能力。

## 验证

- `python -m py_compile server_deploy/core/speech_streaming/omni.py server_deploy/tests/test_omni_voice.py`
- `python -m unittest -v tests.test_omni_voice.OmniVoicePipelineSessionTests.test_start_payload_uses_tenant_avatar_persona tests.test_omni_voice.OmniVoicePipelineSessionTests.test_persona_change_rebuilds_transport_before_next_turn`
- `python -m py_compile server_deploy/core/tenant_avatar/service.py shared_runtime/core/dialog_intent_router.py server_deploy/tests/test_tenant_avatar_persona.py server_deploy/tests/test_dialog_intent_router.py server_deploy/tests/test_person_context_intent.py`
- `python scripts/check-runtime-boundaries.py`
- `python -m unittest -v tests.test_tenant_avatar_persona tests.test_dialog_intent_router.DialogIntentRouterTests.test_assistant_identity_and_abuse_are_chat_without_knowledge_probe tests.test_dialog_intent_router.DialogIntentRouterTests.test_assistant_identity_query_is_chat_intent tests.test_dialog_intent_router.DialogIntentRouterTests.test_assistant_identity_with_event_word_is_not_recall tests.test_dialog_intent_router.DialogIntentRouterTests.test_conversation_recall_is_chat_without_knowledge_probe tests.test_person_context_intent tests.test_omni_voice.OmniVoicePipelineSessionTests.test_start_payload_uses_tenant_avatar_persona tests.test_omni_voice.OmniVoicePipelineSessionTests.test_persona_change_rebuilds_transport_before_next_turn`
