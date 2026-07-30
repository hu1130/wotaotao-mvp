# 2026-07-17 Git 忽略与 Agent 文档清理方案

## 背景

工作区遗留了本地物化部署包目录 `server_deploy_bundle_982075a/`，该目录由部署打包流程生成，不应进入 Git。同时旧的克隆音色操作文档已被删除，但 `AGENT.md` 仍引用该路径，容易误导后续 Agent。

## 处理方案

- `.gitignore` 增加 `server_deploy_bundle_*/`，忽略本地物化部署包目录。
- 保留已加入的 `.ai/` 忽略规则，并补齐文件末尾换行。
- `AGENT.md` 将失效的 `docs/tenant-cloned-omni-voice-optimization.md` 引用改为现存的 superpowers 设计与计划文档。
- 提交旧文档删除，避免仓库中保留过期的克隆音色操作说明。

## 验证

- `git status --short --ignored`
- `git diff --check`

