# 2026-07-20 到场提醒覆盖 repeat 逻辑

## 问题

到场提醒和 repeat 问候各自有触发路径：到场提醒会在签到或首次在场时提前播，repeat 仍可能在员工重新到场时触发，导致用户设置的“以后见到我说...”不能稳定替代普通再次到场问候。同时语音命令缺少撤销到场提醒的入口。

## 原因

`arrival_task` 使用独立的在场状态和离场阈值，未挂到 repeat 的“已签到员工离开后重新入场”判断上；普通记忆删除命令只处理 `person_memory_facts`，没有修改 `person_arrival_tasks` 的 active 状态。

## 修改方案

1. 将到场提醒触发改为 repeat 重入分支的优先路径：目标人重新入场且存在 active 到场任务时，领取并播报 `arrival_task`，不再发 repeat。
2. 保留 `upsert_arrival_task()` 的覆盖语义，同一创建者对同一目标人的新 active 到场任务会替换旧任务。
3. 新增“喊”类到场提醒解析，并兼容方向不一致的中文引号。
4. 新增“取消刚才的到场提醒”和“以后不要再见到我就说这个了”语音撤销命令，将 active 到场任务置为 `cancelled`。
5. 移除旧的 `PERSON_ARRIVAL_TASK_ABSENT_SECONDS` 运行引用和模板配置，统一使用 repeat 的重入阈值。

## 影响

影响服务端远程识别 repeat/arrival_task 触发、人物记忆语音命令解析、人物到场任务数据库状态。签到签退、人脸识别、普通个人记忆删除确认流程不变。

## 验证

- `python -m py_compile server_deploy/core/person_memory/commands.py server_deploy/core/person_memory/service.py server_deploy/core/person_memory/repository.py server_deploy/core/remote_recognition.py server_deploy/core/speech_streaming/pipeline.py`
- `python scripts/check-runtime-boundaries.py`
- `python -m unittest tests.test_person_memory tests.test_person_memory_commands tests.test_arrival_task_repeat_priority tests.test_avatar_event_dispatcher tests.test_arrival_task_speech`
