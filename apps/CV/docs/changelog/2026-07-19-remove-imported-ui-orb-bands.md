# 2026-07-19

## 问题

`/imported-ui/` 页面中心气旋球体仍存在独立的环状 / 条带结构，虽然已不再发白，但和当前大面积雾化流体背景风格不协调，视觉上显得突兀。

## 原因

中心球体 shader 中除了气态旋涡纹理外，还额外叠加了一层 `silkRGB / silkA / silkFront` 丝绸条带合成。该条带层独立于背景流体纹理，容易形成明显的环形结构。

## 修改方案

- 从 `FluidOrb` shader 合成中移除独立丝绸条带层。
- 保留中心半透明气团、旋涡平流和噪声纹理，使中心视觉更接近背景的雾化流体。
- 重新构建并替换 `server_deploy/avatar/imported-ui/` 静态产物。

## 影响

仅影响 `/imported-ui/` 展示页面中心球体视觉；不影响数字人首页、控制台、语音链路或 avatar 服务逻辑。

## 验证

- `node D:\Download\zip\node_modules\next\dist\bin\next build` 构建成功。
- Playwright 访问 `http://127.0.0.1:8787/imported-ui/` 返回 200，页面文本和 2 个 canvas 正常渲染，无横向溢出。
- 截图确认中心条带已移除，仅保留气态旋涡核心。
- 中心区域像素检查：近白像素数量为 0。
- `git diff --check` 通过。
- `npm test` 于 `server_deploy/avatar` 通过，17 项测试全部通过。
- `node --check server_deploy/avatar/server.js` 通过。

## 已知说明

外部 UI 保留 Vercel Analytics 组件，本地 Express 静态服务下仍会请求 `/_vercel/insights/script.js` 并返回 404。该请求不影响页面视觉，本次未移除。
