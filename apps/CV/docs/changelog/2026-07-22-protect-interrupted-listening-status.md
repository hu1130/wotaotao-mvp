# 2026-07-22

## 问题

现场测试发现数字人空打断后没有显示“你说，我听着”。数字人已经停止播报并进入监听，但状态栏仍可能被清空或被空识别状态覆盖。

## 原因

上一版只在 `startVoiceTurn()` 里显示一次“你说，我听着”。但空打断后的真实链路还会继续收到空 listening 事件、空 `asr_partial` 或空 `asr_final`，这些路径会调用 `clearStatusBeforeDeferredSpeech()` 或写入“正在识别”，导致刚显示的打断监听提示很快被清掉。

## 修改方案

- 为被打断后的监听提示增加短暂保护期。
- 抢话确认后先显示“你说，我听着”，并在保护期内阻止空 listening 清空状态栏。
- 空 `asr_partial` 和空 `asr_final` 不再覆盖该提示；识别到真实文本后正常切换到识别文本。
- 增加 `interrupted listening status shown/cleared` 客户端日志，便于现场确认状态链。

## 影响

只影响数字人正在播报时被抢话后的短时状态栏展示。普通空闲监听仍保持不显示状态栏；真实 ASR、LLM 思考、TTS 播放状态仍会正常覆盖该提示。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python scripts/check-runtime-boundaries.py`
