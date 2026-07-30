# 2026-07-19

## 问题

`/imported-ui/` 页面中心区域已经去掉了条带和黄色圆环，但中心视觉仍偏静态装饰，不能明确反馈数字人沟通时的状态变化。

## 原因

外部 UI 的 `FluidOrb` 仅按固定 `audio` 值渲染雾化旋涡，没有区分收听、理解、回复、就绪等沟通阶段；`VoiceOrb` 也没有状态信息呈现。

## 修改方案

- 为中心 `FluidOrb` shader 增加 `uMode` 状态输入。
- 按状态调整旋涡速度、半径、亮度、内收波纹、外放声波和思考脉冲。
- 在 `VoiceOrb` 中新增轻量状态循环，展示 `Listening to visitor intent`、`Understanding request`、`Speaking response`、`Ready for next visitor`。
- 保持粉色雾化背景风格，不恢复黄色圆环、硬质条带或 HUD 装饰。
- 重新构建并替换 `server_deploy/avatar/imported-ui/` 静态产物。

## 影响

仅影响 `/imported-ui/` 展示页面中心反馈视觉；不影响数字人首页、控制台、语音链路或 avatar 服务逻辑。当前为展示页内置演示状态循环，后续可接真实数字人语音状态事件。

## 验证

- `node D:\Download\zip\node_modules\next\dist\bin\next build` 构建成功。
- Playwright 桌面和移动端访问 `http://127.0.0.1:8787/imported-ui/` 返回 200。
- 页面文本正常，2 个 canvas 正常渲染，无横向溢出。
- 状态循环采样覆盖 4 个状态：Listening、Understanding、Speaking、Ready。
- 中心黄色环元素数量为 0。
- `git diff --check` 通过。
- `npm test` 于 `server_deploy/avatar` 通过，17 项测试全部通过。
- `node --check server_deploy/avatar/server.js` 通过。

## 已知说明

外部 UI 保留 Vercel Analytics 组件，本地 Express 静态服务下仍会请求 `/_vercel/insights/script.js` 并返回 404。该请求不影响页面视觉，本次未移除。
