# 2026-07-21 漩涡前台固定音色改为云舟

## 问题

漩涡前台视觉默认使用 Natori，但 `.env.server` 中 `TTS_VOICE_NATORI` 覆盖为 `zh-TW-YunJheNeural`，固定 TTS 和 raw TTS 没有使用预期的 `zh_male_yunzhou_jupiter_bigtts`。

后续线上验证发现，实时问答链路仍然使用数字人/租户克隆音色；漩涡默认语录在固定 TTS 使用火山 provider 时也可能被租户音色覆盖。

## 原因

代码默认值已设置为云舟，但部署环境变量优先级更高，服务器启动时读取 `.env.server` 中的旧 Natori 音色。

浏览器语音 WebSocket 只传租户和设备票据，没有把当前前台展示形态和模型带到 API。API 的 Omni 会话因此只能按可信租户解析克隆音色，无法区分数字人前台和漩涡前台。固定 TTS 在火山模式下同样优先解析租户音色，忽略了 `/tts` 入口传入的 Natori BigTTS speaker。

## 修改方案

将 `TTS_VOICE_NATORI` 改为 `zh_male_yunzhou_jupiter_bigtts`。`MODEL_SPEAKER_NATORI` 原本已是同一音色，保持不变。

- avatar 浏览器在新建和复用语音轮次时传递 `frontdesk_surface` 与 `model_key` 元数据。
- API 在持久语音连接下一轮开始前先应用可信覆盖后的 metadata，再执行 `prepare_next_turn()`，保证音色变化能在下一轮前触发上游连接重建。
- Omni 运行时当 `frontdesk_surface=vortex` 或 `model_key=natori` 时，使用 Natori 模型档案中的 `speaker`，并关闭 clone extra；数字人仍继续按租户音色配置运行。
- 固定 TTS 在火山模式下若入口显式传入 `zh_` 开头的 BigTTS speaker，优先使用该 speaker；Edge voice 名称仍走原来的租户音色分支，避免破坏签到、签退和 arrival_task 的固定播报策略。

## 影响

漩涡前台/Natori 的固定播报和 raw TTS 使用云舟男声。Hiyori 等数字人模型仍使用自己的音色，不与漩涡共用。

漩涡前台的实时问答、默认语录和 raw TTS 都使用 `zh_male_yunzhou_jupiter_bigtts`。人物性格仍走统一的租户人物配置和模型档案，不拆成两套控制台配置。

## 验证

- 检查 `.env.server` 中 `TTS_VOICE_NATORI=zh_male_yunzhou_jupiter_bigtts`
- 同步服务器后检查容器环境和 `/tts-voices`
- `python -m py_compile server_deploy/api/main.py server_deploy/core/speech_streaming/pipeline.py server_deploy/core/speech_streaming/omni.py shared_runtime/core/fixed_tts.py`
- `node --check server_deploy/avatar/avatar.js`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_omni_voice.OmniVoicePipelineSessionTests.test_vortex_surface_uses_natori_voice_without_clone`
- `python -m unittest shared_runtime.tests.test_fixed_tts_voice`
- `python scripts/check-runtime-boundaries.py`

完整 `server_deploy.tests.test_omni_voice` 本地运行到 104 秒超时，新增的漩涡音色覆盖用例已单独通过。
