# 2026-07-20

## 问题

租户管理员在控制台修改数字人人设后，实时对话提示词会更新，但固定事件播报使用的每日语录仍来自平台全局语录池。用户听到的签到、回访、陌生人接待等话术不会体现客户自定义人设。

## 原因

数字人人设保存链路只写入 `tenant_avatar_personas` 并刷新对话系统提示词；每日语录生成和加载链路只维护 `cache/daily_tts_texts.json` 这个全局文件。事件派发虽然带有可信 `tenant_id`，但选词函数没有用租户维度读取语录覆盖。

## 修改方案

- 新增租户级每日语录文件目录 `cache/tenant_daily_tts_texts/`，选词时优先读取当前租户当天语录，缺失时回退平台默认语录。
- 租户保存自定义人设成功后，直接调用每日语录生成模型，写入该租户专属语录文件。
- 租户恢复默认人设时删除租户专属语录文件，后续继续使用平台默认语录。
- 控制台保存人设时展示“正在保存人设，并为数字人生成新人设语录”，生成成功展示“新语录生成成功”；恢复默认展示“已恢复默认人设，继续使用默认语录”。
- Node 控制台代理的人设保存超时调整为 180 秒，避免模型生成期间 10 秒超时。
- 租户人设语录生成新增 `TENANT_DAILY_QUOTES_TIMEOUT_SECONDS`，默认至少 180 秒，避免复杂人设语录在 60 秒全局超时下失败。

## 影响

影响租户控制台数字人人设保存、固定事件播报语录选词和每日语录生成工具。平台全局每日语录仍保持原逻辑；没有自定义人设或已恢复默认的租户继续使用默认语录。

## 验证

- `python -m py_compile shared_runtime/core/daily_tts_texts.py server_deploy/tools/generate_daily_tts_texts.py server_deploy/api/tenant_admin.py server_deploy/core/avatar_event_dispatcher.py server_deploy/tests/test_tenant_avatar_persona.py`
- `node --check server_deploy/avatar/server.js`
- `node --check server_deploy/avatar/control.js`
- `python -m unittest server_deploy.tests.test_tenant_avatar_persona`
- `python scripts/check-runtime-boundaries.py`

## 追加排查

2026-07-20 16:25:11 和 16:25:31，租户 `computer-mine` 保存人设成功并更新到 version 4，但两次租户语录生成都在 60 秒读取阶段超时，因此没有写出 `cache/tenant_daily_tts_texts/computer-mine.json`，事件播报继续回退平台默认语录。手动以 240 秒超时补生成成功后，确认样例语录已符合“兜兜”人设。
