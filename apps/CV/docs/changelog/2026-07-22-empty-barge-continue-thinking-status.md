# 2026-07-22

## 问题

实时沟通中，数字人说话被空打断后会先进入监听态，状态栏显示“我在听呢”。后续系统准备恢复上一段回答或重新生成回答时，准备态文案仍是旧的“我接着想想哈”，现场体验上不能明确表达数字人正在继续处理刚才的问题。

## 原因

空打断恢复链路共用 `EMPTY_BARGE_RESUME_PREPARING_TEXT`。直接续播和重新生成两条路径都会把这个常量传给 `playRawTTS()` 或写入状态栏，因此根因是恢复准备态的统一文案不符合当前交互要求，而不是 ASR、LLM 或 TTS 状态缺失。

## 修改方案

将 `server_deploy/avatar/avatar.js` 中的空打断恢复准备态文案统一改为“正在继续思考你的问题”。这样在“我在听呢”之后、数字人生成或准备播放新回答之前，两条恢复路径都会显示同一状态栏提示。

## 影响

只影响数字人说话被空打断后的恢复准备态状态栏文案，不改变抢话仲裁、ASR 判空、LLM 重新生成、TTS 播放时机和人物记忆规则。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python scripts/check-runtime-boundaries.py`
