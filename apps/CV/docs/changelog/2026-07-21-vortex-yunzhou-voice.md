# 2026-07-21 漩涡前台音色调整

## 问题

漩涡前台运行页没有独立指定模型音色，可能沿用普通数字人页面或本地缓存中的模型，导致漩涡形态下音色不稳定。

## 原因

`/vortex-runtime.html` 和普通数字人页面复用同一套 avatar runtime。旧初始化逻辑优先读取 URL `model`，其次读取 `localStorage.avatarModel`，没有对漩涡前台做专属默认模型约束。

## 修改方案

- 漩涡运行页默认使用 `natori` 模型。
- natori 的默认 TTS 映射统一为 `zh_male_yunzhou_jupiter_bigtts`。
- 漩涡运行页不会把 `natori` 写入普通数字人的模型偏好，避免切回数字人后音色也跟着变成漩涡音色。
- 人物性格、人设、唤醒别名和补充要求继续共用现有租户级“数字人人设”配置；控制台保存一次会同时影响普通数字人和漩涡展示。
- 更新 avatar 脚本版本号，避免浏览器沿用旧缓存。

## 影响

仅影响漩涡前台没有显式 `model` 参数时的默认模型/音色，以及 natori 模型的默认 TTS 映射。普通数字人页面显式选择其他模型不受影响。人设配置不拆分，仍是一套租户级配置。

## 验证

- 已通过：`node --check server_deploy/avatar/avatar.js`
- 已通过：`node --check server_deploy/avatar/server.js`
- 已通过：`python -m py_compile server_deploy/config/voice.py client_deploy/config/voice.py`
- 已通过：`python scripts/check-runtime-boundaries.py`
