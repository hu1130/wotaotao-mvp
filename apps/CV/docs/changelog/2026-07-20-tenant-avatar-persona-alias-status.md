# 2026-07-20

## 问题

租户管理员保存数字人人设后，弹窗不会自动回到控制台主页面，用户看不到主页面“数字人人设”右侧的生成状态。再次打开人设弹窗时，唤醒别名输入框会混入系统默认的“叮当、小叮当”；对话模型也会把默认名字当成可自称名字，导致问“你是谁”时回答成叮当，或同时说也可以叫新名字。

## 原因

人设服务把“用于运行时识别的有效唤醒名”和“管理员手动保存的别名”混在同一个 `wakeAliases` 字段返回。自定义名字后 `_resolve_wake_aliases()` 仍继续追加默认 `VOICE_ASSISTANT_WAKE_ALIASES`，这些默认别名又进入系统提示词，污染模型自我身份。

## 修改方案

- `AvatarPersonaSettings` 新增 `custom_wake_aliases`，接口返回 `customWakeAliases` 给控制台表单使用。
- 自定义数字人名字时，运行时唤醒别名只包含新名字、派生小名和管理员自定义别名，不再追加默认“叮当、小叮当”；历史已污染到数据库里的默认别名也会在解析时过滤。
- 系统提示词和聊天提示词明确“正式名字只有当前名字”，且不再在负向提示里重复具体默认旧名字，避免模型自称默认名字。
- 控制台保存人设后立即关闭弹窗回到主控制台，右侧状态实时显示“正在保存人设，正在为数字人生成新人设语录”和最终结果。

## 影响

影响租户自定义数字人人设、人设弹窗回填、对话身份提示和控制台保存交互。默认人设未修改的租户仍继续使用默认名字和默认唤醒别名。

## 验证

- `python -m py_compile server_deploy/core/tenant_avatar/models.py server_deploy/core/tenant_avatar/service.py server_deploy/api/tenant_admin.py server_deploy/tools/generate_daily_tts_texts.py server_deploy/tests/test_tenant_avatar_persona.py`
- `node --check server_deploy/avatar/control.js`
- `python -m unittest server_deploy.tests.test_tenant_avatar_persona`

## 追加验证

- 新增历史污染数据测试：数据库已保存 `兜兜、小兜兜、叮当、小叮当` 时，解析后的有效唤醒别名和表单回填别名只保留 `兜兜、小兜兜`，聊天提示词不再包含 `叮当`。
