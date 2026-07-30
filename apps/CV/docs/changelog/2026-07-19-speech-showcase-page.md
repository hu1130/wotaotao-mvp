# 2026-07-19

## 问题

需要在不影响原数字人页面的前提下，新增一个参考语音交互视觉稿风格的展示页面，并提供页面切换入口。

## 原因

原 `server_deploy/avatar/index.html` 承载 Live2D 数字人、语音链路和 WebSocket 状态，不适合直接改造成纯展示页；直接重写首页会扩大对现有交互链路的影响。

## 修改方案

新增独立静态页 `speech-showcase.html`、`speech-showcase.css`、`speech-showcase.js`，用玻璃拟态导航、柔焦空间背景、Canvas 声场核心和底部通话控制台复刻参考图的视觉方向。

在原首页只新增一个轻量切换入口，跳转到语音展示页，不修改 `avatar.js` 业务逻辑。

后续按视觉方案将展示页替换为 React + Three.js 实现：

- 新增 `src/speech-showcase/main.jsx` 和 `src/speech-showcase/styles.css` 作为源码。
- 新增 `build:showcase` 构建脚本，用 esbuild 打包 React、ReactDOM 和 Three.js 到静态产物。
- Three.js 负责透明玻璃球、液态内核、香槟金环、shader 流体丝带、丝线层和粒子场；React 负责导航、状态文案、能力标签和底部控制台。
- 运行时仍由 avatar 静态服务直接发布 `/speech-showcase.html`，不依赖外部 CDN。

本次进一步修复 `image_15.png` 对照下的视觉问题：

- 根因：旧中心内核使用正弦条纹 shader，视觉上像扁平条纹晶体；主 ring 角度近似侧向，呈现成横线；声波主要由透明面片和细线构成，粘性和折射质感不足。
- 修改：中心核心替换为多层 liquid-metal/metaball 结构，包含透明玻璃壳、液态内核、重叠粘性球群、管状内部电流和 gooey tendril。
- 修改：左右声波改成清晰 TubeGeometry 流体管线，触须使用有厚度的物理材质管线连接核心与声波。
- 修改：主 ring 改为面向镜头的高折射香槟金圆环，保留轻微倾斜和动态扫光。
- 修改：保持所有指定文案逐字一致，强化顶部/底部 glassmorphism、中文能力标签清晰度、按钮和图标金属高光、深洋红背景层次。

## 影响

影响范围限定在 avatar 静态资源：

- 原 `/` 和 `/index.html` 仍使用原 Live2D 页面。
- 新页面为 `/speech-showcase.html`。
- 未新增后端接口、未修改语音会话和租户鉴权逻辑。
- `server_deploy/avatar/package.json` 新增 React、ReactDOM、Three.js 依赖和 esbuild 开发依赖；部署环境需要按 lockfile 安装依赖后运行 `npm run build:showcase` 生成静态产物。

## 验证

- `node --check server_deploy/avatar/speech-showcase.js`
- `git diff --check`
- 本地静态服务验证 `/speech-showcase.html` 与 `/index.html` 返回 200，首页包含新切换入口与更新后的 `styles.css` 缓存版本。
- 本地静态服务打开 `/speech-showcase.html`，使用 Chrome + Playwright 截图验证桌面 1365×768 和移动 390×844 视口。
- Canvas 像素采样确认声场画布非空；移动端确认无横向溢出，麦克风按钮为 66×66 圆形。
- React + Three.js 替换后重新执行 `npm run build:showcase`、`node --check speech-showcase.js`、`git diff --check`。
- Chrome + Playwright 验证桌面和移动端均无控制台错误，WebGL Canvas 非空，无横向溢出。
- 液态核心修复后重新执行 `npm run build:showcase` 和 `git diff --check`，并用 Chrome + Playwright 验证指定文案逐字一致、WebGL Canvas 非空、桌面/移动端无横向溢出。
