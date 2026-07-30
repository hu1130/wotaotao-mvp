# 2026-07-15 叮当唤名识别改动说明（Agent1）

## 背景

用户要求给数字人起名为“叮当”，并要求用户喊“叮当”时，数字人能知道是在叫它。

## 本次方案

采用温和唤名模式：

- 数字人默认名称改为“叮当”。
- 支持唤名别名：`叮当`、`小叮当`。
- 用户只说“叮当 / 叮当你在吗 / 小叮当”时，直接回复“我在。”。
- 用户说“叮当 + 指令”时，服务端去掉唤名部分后继续走原来的记忆、人物上下文、动作、RAG、LLM 链路。
- 不强制要求每句话都喊“叮当”，避免影响现有对话体验。

## 涉及文件

- `server_deploy/config/voice.py`
  - 新增 `VOICE_ASSISTANT_NAME`、`VOICE_ASSISTANT_WAKE_ALIASES`、`VOICE_ASSISTANT_WAKE_ENABLED`、`VOICE_ASSISTANT_WAKE_REPLY`。
  - `REALTIME_DIALOG_BOT_NAME` 默认改为 `叮当`。
  - 实时语音和文本对话系统提示加入“用户喊叮当是在叫你”。
- `server_deploy/core/dialog_wake_name.py`
  - 新增唤名解析模块，统一输出是否命中、是否只是叫名、去掉唤名后的指令文本。
- `server_deploy/core/speech_streaming/pipeline.py`
  - 级联语音链路接入唤名解析。
  - 命中唤名时输出 `wake_name` 调试事件，并记录日志。
- `server_deploy/core/speech_streaming/omni.py`
  - Omni 链路接入同一套唤名解析。
  - “叮当 + 指令”使用去掉唤名后的文本进入业务路由。
- `server_deploy/core/dialog_chat.py`
  - 文本对话中只输入“叮当”时走本地快速回复“我在。”。
  - “你是谁/你叫什么”快速回复改为“我是叮当...”。
- `server_deploy/.env.server`
  - 已同步线上环境名为“叮当”。
- `server_deploy/.env.server.example`
  - 已补充唤名相关环境变量示例。
- `server_deploy/tests/test_dialog_wake_name.py`
  - 新增解析单测。

## Agent1 自检

已执行：

```powershell
python -m unittest tests.test_dialog_wake_name
python -m compileall config core\dialog_wake_name.py core\dialog_chat.py core\speech_streaming\pipeline.py core\speech_streaming\omni.py
```

结果：

- `test_dialog_wake_name`：5 条通过。
- 编译检查通过。

## 建议 Agent2 测试点

1. 语音只喊“叮当”，状态栏应出现 ASR，数字人应回复“我在。”并播放音频。
2. 语音说“叮当，以后我一过来你就跟我说 are you ok”，应能创建到场触发任务。
3. 用户短暂离开 1-2 秒再回来，应触发前一条到场任务。
4. 语音说“叮当，帮我查一下公司资料”，应去掉“叮当”后进入知识库/模型链路。
5. 文本输入“叮当”，应直接回复“我在。”。
6. 语音不喊“叮当”的普通对话应保持原有行为。

## 注意

本轮不涉及 EXE 打包，交由测试侧处理。
