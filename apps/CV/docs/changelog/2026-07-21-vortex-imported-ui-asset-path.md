# 2026-07-21 漩涡页静态资源路径修复

## 问题

切换到漩涡页后只显示 Logo、Features、History 和 Speech Interaction，其余背景与交互区域空白。

## 原因

`imported-ui` 作为静态页面挂在 `/imported-ui/` 下，但 Next 导出的 HTML 仍引用根路径 `/_next/static/...`。服务器没有在根路径提供这些构建资源，导致 CSS/JS chunk 404，页面无法完成客户端 hydration。

## 修改

- `frontend_sources/imported-vortex-frontdesk/next.config.mjs` 增加 `basePath: "/imported-ui"` 与 `assetPrefix: "/imported-ui"`。
- 移除漩涡页模板占位头部与 “Speech Interaction” 大标题，避免切换后显示 Logo / Features / History 等占位内容。
- 重新构建漩涡静态页并同步到 `server_deploy/avatar/imported-ui`。

## 验证

- `pnpm build`
- 检查导出的 `index.html` 不再引用根路径 `/_next/static`。
- 服务器检查 `/imported-ui/_next/static/...` 资源返回 200。
