# Dingdang Wake Reply Copy

## 问题

用户喊“叮当”时，数字人当前快速回复是“我在。”，希望改成更自然的“我在呢”。

## 修改方案

- 将 `VOICE_ASSISTANT_WAKE_REPLY` 默认值改为“我在呢”。
- 同步服务端环境示例和唤醒词快速回复测试。
- 服务器实际 `.env.server` 也需要把同名变量改为“我在呢”，否则环境变量会覆盖代码默认值。

## 影响

仅影响唤醒名且无后续指令时的快速回复；“叮当，帮我……”这类带命令的句子仍按原路由处理。

## 验证

- `python -m unittest server_deploy.tests.test_dialog_wake_name`
- `python -m py_compile server_deploy/config/voice.py server_deploy/core/dialog_chat.py server_deploy/core/speech_streaming/pipeline.py server_deploy/core/speech_streaming/omni.py`
