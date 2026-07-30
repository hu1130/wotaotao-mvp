# 2026-07-20 人物记忆不再因上下文窗口溢出退场

## 问题

人物记忆 worker 已经能从真人与数字人的完整语音轮次中提炼事实并生成 embedding，但仓库层会在每个人 active facts 超过 `PERSON_MEMORY_MAX_FACTS` 后，把排序靠后的事实标记为 `superseded`。这些事实虽然没有物理删除，但不会再参与个人记忆检索，容易被误解为“记忆丢了”。

## 原因

旧实现把“上下文窗口最多放几条记忆”和“个人长期记忆库最多保留多少条 active fact”混在了一起。实际需要的是：每轮只取少量高相关/高置信记忆进入 prompt，但长期知识库里应保留更多带 embedding 的个人事实，后续按问题检索。

## 修改方案

- 取消 `apply_extraction()` 中超过上限后标记 `superseded` 的逻辑。
- 保留 `PERSON_MEMORY_RETRIEVAL_TOP_K=6` 作为每次问题相关记忆注入上限。
- 将 `PERSON_MEMORY_SESSION_TOP_K` 默认值调整为 6，让入场会话快照也只取 6 条。
- 新增迁移 version 4，把历史上因上限被标记为 `superseded` 的事实恢复为 `active`。
- 审计日志继续记录本次提炼后的 active fact 总数，方便观察个人知识库增长。

## 影响

员工与数字人的对话仍先落入 `person_conversation_turns/messages`，worker 提炼出的事实会持续保存在 `person_memory_facts`。上下文不会无限膨胀，每次只取 top 6；超过 top 6 的事实仍留在个人记忆知识库中，可被后续语义检索命中。

## 验证

已新增单测覆盖 top_k 语义、禁止溢出事实被 `superseded`、历史 `superseded` 迁移恢复。
