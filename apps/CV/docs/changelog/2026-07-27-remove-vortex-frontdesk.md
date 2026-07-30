# 2026-07-27 删除漩涡前台界面

## 问题

数字人前台同时保留 Live2D 数字人页面和导入的漩涡前台界面。漩涡界面包含独立 Next/React 源码、已构建静态包、隐藏运行内核页、控制台切换入口，以及服务端 Omni 对 `frontdesk_surface=vortex` 的特殊音色策略。

## 原因

漩涡前台是第二套展示 surface，和当前数字人前台的主链路并列存在。控制台可下发 surface 切换命令，avatar 运行时也会识别 `/imported-ui/` 和 `/vortex-runtime.html`，导致前台展示和服务端语音配置有额外分支。

## 修改方案

删除 `frontend_sources/imported-vortex-frontdesk/` 导入源码、`server_deploy/avatar/imported-ui/` 静态包和 `server_deploy/avatar/vortex-runtime.html`。控制台移除前台形态切换 UI，只保留数字人模型切换。avatar 运行时固定返回 `avatar` surface，不再处理 imported-ui iframe 消息或 `SWITCH_FRONTDESK_SURFACE` 命令。服务端 Omni 去掉漩涡/Natori 专用音色分支，旧请求即使携带 `frontdesk_surface=vortex` 也归一为 `avatar` 并继续走租户音色配置。

## 影响

数字人首页 `/`、展示模式 `?display=1`、控制台模型切换、语音票据和租户语音配置保持原链路。历史 `/imported-ui/` 和 `/vortex-runtime.html` 不再作为前台入口提供。平台管理员和企业控制台的租户/设备管理 API 不属于漩涡前台设计，本次保留。

## 验证

- 关键词复查确认手写代码不再包含漩涡前台入口、静态包引用或切换命令。
- 新增/调整 Omni 测试，确认历史 `frontdesk_surface=vortex` 元数据会归一为 `avatar` 并继续使用租户音色服务。
- 待执行本地语法检查和针对性测试。
