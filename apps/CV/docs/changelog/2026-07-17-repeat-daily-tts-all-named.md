# 2026-07-17 Repeat 每日语录全部带姓名

## 问题

每日语录生成器原先要求 `repeat` 生成 10 条，其中 3 条带姓名、7 条不带姓名。运行时虽然会过滤出带姓名模板播放，但生成结果本身不符合后续希望所有 repeat 都带称呼的规则。

## 原因

`NAME_PLACEHOLDER_COUNTS` 和生成提示词仍保留旧策略，fallback 文案也混有不带 `{}` 的 repeat 句。

## 修改方案

- 将服务端和客户端生成器里的 `repeat` 配额改为 `with_name=10`、`without_name=0`。
- 修改 LLM 生成提示，明确 repeat 的 10 句必须每一句都带 `{{name}}`。
- 修改 fallback repeat 文案，保证 10 条全部包含 `{}`。

## 影响

以后重新生成 `daily_tts_texts.json` 时，repeat 文案池本身就会全部带姓名，不再只依赖运行时过滤。

## 验证

- `python -m py_compile server_deploy/tools/generate_daily_tts_texts.py`
- `python -m py_compile client_deploy/tools/generate_daily_tts_texts.py`
- 静态检查确认生成器中 `repeat` 配额为 10/0。
