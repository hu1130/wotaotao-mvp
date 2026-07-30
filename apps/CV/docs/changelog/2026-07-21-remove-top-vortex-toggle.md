# 2026-07-21 删除控制台顶部漩涡切换按钮

## 问题

企业控制台顶部 header 有一个“切到漩涡前台/切换前台”快捷按钮，下方“前台与数字人实例”区域已经有完整的前台展示形态切换入口，两个入口功能重复。

## 原因

顶部按钮和下方切换器都发送同一个 `SWITCH_FRONTDESK_SURFACE` 控制命令。下方切换器展示了“数字人/漩涡前台”两个状态和说明，是更完整的入口；顶部按钮只是二态快捷切换，容易造成界面重复。

## 修改方案

- 删除 `control.html` header 中的 `frontdesk-toggle-button`。
- 删除 `control.js` 中顶部切换按钮的 DOM 引用、状态更新和点击绑定。
- 保留下方 `frontdesk-surface-switcher`，继续作为唯一的前台展示形态切换入口。
- 更新 `control.js` 加载版本，避免浏览器沿用旧脚本。

## 影响

只影响企业控制台顶部 UI。前台展示形态切换命令、下方切换入口、数字人模型切换和漩涡前台运行逻辑不变。

## 验证

- `node --check server_deploy/avatar/control.js`
