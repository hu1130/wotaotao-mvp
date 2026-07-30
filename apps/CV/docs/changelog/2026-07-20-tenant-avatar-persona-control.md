# 2026-07-20

## 问题

数字人的名字、性格和说话语气只能通过服务端环境变量配置。控制台没有租户级入口，企业用户无法为自己的数字人做个性化设置；即使前端临时展示了名字，也不会影响真实语音对话提示词。

## 原因

当前语音链路使用静态配置：

- cascade 文本/语音对话使用 `DIALOG_CHAT_SYSTEM_PROMPT`。
- Omni 实时对话使用 `REALTIME_DIALOG_SYSTEM_ROLE` 和 `REALTIME_DIALOG_BOT_NAME`。
- 唤名解析使用 `VOICE_ASSISTANT_WAKE_ALIASES`。

这些配置在进程启动时固定，缺少按租户持久化、管理接口和运行时解析。

## 修改方案

- 新增 `tenant_avatar_personas` 租户级人设表，保存数字人名字、唤醒别名、性格、说话语气和补充要求。
- 新增租户管理员接口 `GET/PUT /api/v1/tenant-admin/avatar-persona`，控制台通过 `/tenant/avatar-persona` 代理读写。
- 新增只读接口 `GET /api/v1/avatar/persona`，允许数字人 avatar-session 读取当前租户公开人设。
- cascade 对话、Omni 实时语音和唤名解析均改为按租户解析人设；未设置时继续使用默认环境变量配置。
- 控制台“运行控制”新增“数字人人设”面板，可保存、恢复默认并显示当前配置状态。

## 影响

- 影响数字人普通聊天、知识库问答、Omni 实时对话、语音唤名和控制台展示。
- 配置按 `tenant_id` 隔离；控制台只能读写当前管理员所属租户。
- 空配置会被视为未设置，运行时回退默认人设。

## 验证

- 新增 `server_deploy/tests/test_tenant_avatar_persona.py` 覆盖默认回退、自定义名字/别名和空配置恢复默认。
- 已运行 Python 编译、目标单测和 Node 语法检查。
