# 2026-07-19

## 问题

`/imported-ui/` 页面中心气旋外还有两个黄色 / 金色圆环，和当前粉色雾化流体背景不协调，视觉上显得突兀。

## 原因

外部 UI 的 `VoiceOrb` 组件在 `FluidOrb` 外层额外叠加了两个 `border-amber` 光环元素，包括旋转光环和内层细环。

## 修改方案

- 从 `VoiceOrb` 组件中移除两个黄色光环 DOM 元素。
- 保留中心 `FluidOrb` WebGL 雾化旋涡。
- 重新构建并替换 `server_deploy/avatar/imported-ui/` 静态产物。

## 影响

仅影响 `/imported-ui/` 展示页面中心气旋装饰；不影响数字人首页、控制台、语音链路或 avatar 服务逻辑。

## 验证

- `node D:\Download\zip\node_modules\next\dist\bin\next build` 构建成功。
- Playwright 访问 `http://127.0.0.1:8787/imported-ui/` 返回 200，页面文本和 2 个 canvas 正常渲染，无横向溢出。
- 截图确认中心两个黄色圆环已移除。
- 页面产物中 `border-amber` / 金色环相关类名数量为 0。
- `git diff --check` 通过。
- `npm test` 于 `server_deploy/avatar` 通过，17 项测试全部通过。
- `node --check server_deploy/avatar/server.js` 通过。

## 已知说明

外部 UI 保留 Vercel Analytics 组件，本地 Express 静态服务下仍会请求 `/_vercel/insights/script.js` 并返回 404。该请求不影响页面视觉，本次未移除。
