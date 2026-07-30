# 2026-07-23 实时语音业务静音控制

## 问题

用户要求说“别说话了”“小嘴巴”“别叫了”“静音”后，数字人暂停实时沟通；数字人需要先反馈已开启静音，并提示可以喊当前数字人名字唤醒。静音期间状态栏应持续显示“静音中，喊{名字}唤醒我”，且用户喊数字人名字后解除静音。

## 原因

原系统只有唤名快速回复和前端麦克风静音按钮。唤名只负责“叫名字”识别，前端按钮只控制本地麦克风采集，两者都不是服务端业务级暂停实时沟通状态。匿名或短连接场景下，如果只把静音存在单个 WebSocket 会话里，连接关闭后还会丢失状态。

Omni 链路还存在一条上游默认回答通道：服务端收到 ASR 后，火山 Omni 可能已经开始默认生成。静音控制如果只设置业务状态、不主动截断默认通道，用户仍可能听到“好的，那我不打扰你”这类默认回答；静音后再次说“你好”时，也可能被默认通道抢先回答。

## 修改方案

- 新增 `server_deploy/core/dialog_silence.py`，统一解析业务静音命令、静音中唤名恢复、静音中非唤名抑制，并按当前租户数字人人设生成动态名字提示。
- 在 `VoicePipelineSession` 基类接入 `tenant_id + device_id` 级静音状态，级联语音和 Omni 语音复用同一套控制逻辑。
- Omni 路由入口先处理静音控制；静音/解除静音控制轮次不写入人物长期记忆。
- 静音开启、静音中抑制和唤醒反馈前，Omni 会主动发送 `client_interrupt` 截断默认生成，并清理默认回答缓冲，防止上游默认回答漏播。
- avatar 前端新增 `dialog_silence` 状态处理，静音中保护状态栏显示；固定语录播放期间仍允许展示固定语录，播完恢复静音提示。

## 影响

影响浏览器实时语音 `/api/v1/dialog/voice-stream` 的级联和 Omni 两条后端。静音状态按租户和设备隔离，当前进程内持久；服务重启后状态会清空。固定语录、欢迎语和受保护语音仲裁不改变。

## 验证

- `python -m unittest tests.test_dialog_silence tests.test_dialog_wake_name`
- `python -m unittest tests.test_dialog_silence tests.test_dialog_wake_name tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silence_interrupts_omni_default_generation tests.test_omni_voice.OmniVoicePipelineSessionTests.test_dialog_silenced_followup_interrupts_and_drops_default_audio`
- `python -m compileall core\dialog_silence.py core\speech_streaming\pipeline.py core\speech_streaming\omni.py tests\test_dialog_silence.py`
- `npm test`
- `node --check avatar.js`
