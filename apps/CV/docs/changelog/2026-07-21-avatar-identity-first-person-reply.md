# 2026-07-21 数字人身份问答第一人称修复

## 问题

用户第一句问“你叫啥”时，数字人回答成“你叫小丑”，语义方向错误；部分身份问法还可能被唤醒词逻辑误判，只返回“我在呢”。身份类问题需要保留 AI 生成，以便人物性格自然生效，但不能进入企业知识 RAG。

## 原因

租户人物提示词中写有“只回答你叫{assistant_name}”，会直接诱导模型输出第二人称表达。实时语音链路此前依赖意图路由或 embedding 判断身份问答，规则不够显式；同时快速回复函数先判断唤醒词，若别名和“你”一类短词冲突，会在身份意图前提前返回唤醒话术。

## 修改方案

将人物提示词改为明确要求第一人称回答“我叫{assistant_name}”或“我是{assistant_name}”，并禁止“你叫{assistant_name}”。共享意图路由新增数字人身份问答规则，显式判定为 chat，不访问企业知识库。快速回复函数改为先规整问题并识别身份意图；身份问题返回空交给 AI 生成，避免固定话术，也避免被唤醒词短回复截断。

## 影响

影响数字人文本对话和实时语音对话中的身份问答。普通唤醒、寒暄、签到签退 repeat、arrival_task 直接播放链路不改变。

## 验证

- `python -m py_compile shared_runtime/core/dialog_intent_router.py server_deploy/core/tenant_avatar/service.py server_deploy/core/dialog_chat.py server_deploy/core/speech_streaming/omni.py`
- `PYTHONPATH=server_deploy python -m unittest server_deploy.tests.test_tenant_avatar_persona server_deploy.tests.test_dialog_intent_router server_deploy.tests.test_dialog_wake_name`
- `python scripts/check-runtime-boundaries.py`
- 手测 `你叫啥？` 和 `你的名字是什么？` 本地快速回复返回空，并由意图路由判为 `chat/keyword_assistant_identity`
- 手测单独唤醒 `小丑` 仍返回 `我在呢`
