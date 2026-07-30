# 2026-07-19

## 问题

需要将 `D:\Download\zip` 中外部前端构建平台生成的语音交互 UI 接入当前 avatar 项目，并且不能破坏原有页面和外部 UI 自身的视觉效果。

## 原因

外部 UI 是一个独立 Next.js 项目源码，不能直接被当前 Express 静态服务按源码方式访问；需要先导出为静态资源，再挂载到 avatar 静态目录下。

## 修改方案

- 将外部 UI 按 `/imported-ui/` 子路径构建为静态产物，并复制到 `server_deploy/avatar/imported-ui/`。
- 在 avatar 首页左上角页面切换器中新增 `外部UI` 入口，同时保留原数字人和语音展示入口。
- 修正导入产物中的图标资源路径，避免子路径部署时 favicon 请求落到站点根路径。

## 影响

新增页面路径为 `/imported-ui/`，不改变现有数字人首页、控制台、语音展示页的业务逻辑。导入 UI 保持外部构建平台原始组件和样式效果。

## 验证

- `node D:\Download\zip\node_modules\next\dist\bin\next build` 构建成功。
- `http://127.0.0.1:8787/imported-ui/` 返回 200，CSS 和图标资源返回 200。
- Playwright 检查桌面和移动端视口：页面可渲染，存在 2 个 canvas，无横向溢出。
- 截图像素检查确认画面非空。
- `git diff --check` 通过。
- `npm test` 于 `server_deploy/avatar` 通过，17 项测试全部通过。
- `node --check server_deploy/avatar/server.js` 通过。

## 已知说明

外部 UI 保留了 Vercel Analytics 组件；在本地 Express 静态服务下会请求 `/_vercel/insights/script.js` 并返回 404。该请求不影响 UI 渲染，因用户要求保留外部页面效果，本次未移除该组件。
