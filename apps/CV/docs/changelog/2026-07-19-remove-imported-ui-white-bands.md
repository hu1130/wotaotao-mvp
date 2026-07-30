# 2026-07-19

## 问题

`/imported-ui/` 页面中心气旋球体的流动条高光过亮，视觉上形成明显白色带状结构，破坏整体粉色流体风格。

## 原因

外部 UI 的 `FluidOrb` shader 在绸带层中使用了接近白色的高光颜色，并额外叠加较高亮度，导致前景条带在中心球体上显得发白。

## 修改方案

- 保留中心气旋的缠绕流动效果。
- 将绸带材质的亮部从白色压回玫瑰金 / 洋红色范围。
- 限制高光上限，避免再次产生刺眼白色流动条。
- 重新构建并替换 `server_deploy/avatar/imported-ui/` 静态产物。

## 影响

仅影响外部 UI 展示页 `/imported-ui/` 的中心球体视觉高光；不影响 avatar 业务逻辑、控制台或原数字人页面。

## 验证

- `node D:\Download\zip\node_modules\next\dist\bin\next build` 构建成功。
- Playwright 访问 `http://127.0.0.1:8787/imported-ui/` 返回 200，页面文本和 2 个 canvas 正常渲染。
- 截图中心区域像素检查：近白像素数量为 0。
- `git diff --check` 通过。
- `npm test` 于 `server_deploy/avatar` 通过，17 项测试全部通过。

## 已知说明

外部 UI 保留 Vercel Analytics 组件，本地 Express 静态服务下仍会请求 `/_vercel/insights/script.js` 并返回 404。该请求不影响页面视觉，本次未移除。
