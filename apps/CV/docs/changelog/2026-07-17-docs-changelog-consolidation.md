# 2026-07-17 Docs 变更记录归档

## 问题

`docs/` 根目录下散落多个日期型变更记录，和新增的 `architecture/`、`deployment/`、`changelog/` 分类结构不一致。

## 原因

历史变更记录一直直接写在 `docs/` 根目录，后续 Agent 查找文档时容易同时面对架构、部署、计划和变更记录，降低检索效率。

## 修改方案

- 将 `docs/20*.md` 日期型变更记录统一移动到 `docs/changelog/`。
- 更新 `.codex/AGENT.md`，历史变更只指向 `docs/changelog/`。
- 更新 superpowers 计划中指向旧 `docs/YYYY-MM-DD-*.md` 的引用。

## 影响

`docs/` 根目录只保留分类目录，文档入口更清晰。

## 验证

- 确认 `docs/` 根目录只剩 `architecture/`、`changelog/`、`deployment/`、`superpowers/`。
- 全文搜索确认不存在 `docs/YYYY-MM-DD-*.md` 旧路径引用。

## 后续入口

新增根目录 `AGENTS.md` 作为新 Agent 的标准入口，`AGENT.md` 保留为兼容旧习惯的短入口。
