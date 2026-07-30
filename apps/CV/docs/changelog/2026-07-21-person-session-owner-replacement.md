# 2026-07-21 人物会话缺席主人被新人替换时不再沿用旧身份

## 问题

旧会话主人离开后，`PersonConversationManager` 会进入 `OWNER_GRACE`，默认保留旧 owner 15 秒。这个防抖用于处理摄像头短暂丢脸，但当第二个已识别的人已经站到数字人正前方时，语音链路仍会读取旧 owner 上下文，导致“你知道我是谁吗”被回答成上一位主人。

## 根因

旧逻辑在 owner 缺席期间只记录新候选人，必须等 `PERSON_SESSION_ABSENT_SECONDS` 到期后才清理旧 owner 并激活候选人。`OWNER_GRACE` 快照仍暴露旧 `owner_id / owner_name / conversation_id`，所以 voice websocket 会继续把本轮问题绑定旧人物记忆。

## 修改

- owner 缺席且出现新的已识别候选人时，对外快照进入 `CANDIDATE`，不再暴露旧 owner 和旧 conversation，避免新人的语音继续继承旧人物记忆。
- 新候选人稳定达到 `PERSON_SESSION_ACQUIRE_SECONDS` 后，立即以 `owner_replaced` 结束旧会话并创建新会话，不再等待 15 秒。
- 没有替换候选人时，仍保留原有 `PERSON_SESSION_ABSENT_SECONDS` 缺席防抖，避免摄像头短暂丢脸导致会话抖动。

## 验证

```powershell
$env:PYTHONPATH='D:\CV_deploy\dist_deploy\server_deploy;D:\CV_deploy\dist_deploy\shared_runtime'
python -m unittest server_deploy.tests.test_person_sessions
python -m unittest server_deploy.tests.test_runtime_isolation
python -m py_compile server_deploy/core/person_sessions/manager.py server_deploy/tests/test_person_sessions.py
```

结果：人物会话单测 7 条通过，运行时隔离单测 6 条通过，语法编译通过。
