# 人物到场触发任务改造 Agent1 交付文档

## 背景

用户希望能通过自然语音设置固定到场指令，例如：

- “以后我一过来你就跟我说‘are you ok’”
- “待会儿小王员工来了，骂他两句”

要求短暂离开画面 1-2 秒后回来也要触发，且不能只写死成固定语录。

## 实现方案

1. 新增通用 `arrival_task` 语音命令类型。
   - 引号内文本按精确播报保存，例如 `are you ok`。
   - 非引号内容按到场执行指令保存，例如 `骂他两句`，当前执行方式为转述提醒：`小王，小羊让我提醒你：骂他两句`。
   - `待会儿/等会儿/一会儿` 识别为一次性任务，触发后置为 `done`。
   - `以后/之后/往后` 识别为重复任务。

2. 新增 PostgreSQL 表 `person_arrival_tasks`。
   - 存储创建人、目标人、内容、是否精确播报、是否重复、触发次数和最后触发时间。
   - 同一租户、同一创建人、同一目标、同一动作的新任务会替换旧 active 任务。
   - 触发时使用 `FOR UPDATE SKIP LOCKED` 领取，避免并发重复播报。

3. 识别服务接入到场触发。
   - 首次在场初始化、签到成功、离开后重新出现都会尝试领取任务。
   - 普通回场欢迎仍走原 `CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS`。
   - 到场任务新增独立阈值 `PERSON_ARRIVAL_TASK_ABSENT_SECONDS=1.0`，用于满足短暂离开回来也触发。

4. 动态播报接入现有 avatar speech 通道。
   - 新增 `RemoteAvatarEventDispatcher.emit_custom_speech()`。
   - 发送 `type=speech,event_type=arrival_task,text=...` 到 avatar `/event`。
   - Avatar 端已有 `playRawTTS()` 处理，会继续走克隆音色 raw TTS，保持全项目音色统一。

## 主要改动文件

- `server_deploy/core/person_memory/commands.py`
- `server_deploy/core/person_memory/migrations.py`
- `server_deploy/core/person_memory/repository.py`
- `server_deploy/core/person_memory/service.py`
- `server_deploy/core/speech_streaming/pipeline.py`
- `server_deploy/core/remote_recognition.py`
- `server_deploy/core/avatar_event_dispatcher.py`
- `server_deploy/core/person_identity.py`
- `server_deploy/config/camera.py`
- `server_deploy/.env.server.example`

## 本地验证

已执行：

```bash
PYTHONPATH=server_deploy python -m compileall server_deploy/core/person_memory server_deploy/core/speech_streaming/pipeline.py server_deploy/core/avatar_event_dispatcher.py server_deploy/core/remote_recognition.py server_deploy/config/camera.py
PYTHONPATH=server_deploy python -m unittest server_deploy.tests.test_person_memory server_deploy.tests.test_avatar_event_dispatcher -v
```

结果：编译通过，相关单测 10 条通过。

全量 `python -m unittest discover -s server_deploy/tests -v` 在本地 124 秒超时，未作为通过结论。

## 服务器验证

已同步到服务器 `myserver:/opt/server_deploy`，并执行：

```bash
python3 -m compileall core/person_memory core/speech_streaming/pipeline.py core/avatar_event_dispatcher.py core/remote_recognition.py config/camera.py
docker compose --env-file .env.server -f docker-compose.deploy.yml config --quiet
docker compose --env-file .env.server -f docker-compose.deploy.yml build api memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python -m unittest tests.test_person_memory tests.test_avatar_event_dispatcher -v
curl -fsS http://127.0.0.1:8000/health
```

结果：

- API、avatar、memory-worker、nginx 均已运行，API/nginx/avatar 为 healthy。
- `person_arrival_tasks` 表已存在。
- 容器内相关单测 10 条通过。
- `/health` 返回 `{"ok":true,"service":"company-integration-api"}`。

## 建议 Agent2 测试点

1. 用户说：“以后我一过来你就跟我说‘are you ok’”
   - 服务端应写入 active 重复任务。
   - 用户离开画面约 1-2 秒后回来，应自动播报 `are you ok`。

2. 用户说：“待会儿小王员工来了，骂他两句”
   - 服务端应写入 non-repeat 任务，目标名为 `小王`，内容为 `骂他两句`。
   - 小王出现时应播报转述提醒。
   - 触发后任务状态应变为 `done`，再次出现不重复播报。

3. 用户重新设置同一目标任务。
   - 旧 active 任务应变为 `replaced`，只保留最新 active 任务。

4. Avatar 日志应能看到 `event_type=arrival_task` 的 speech 事件。
   - 客户端状态栏应按播报文本显示。
   - 音频应走克隆音色 raw TTS。

## 注意事项

- 本次不涉及 EXE 打包，按项目约定交由测试处理。
- 非精确任务当前先做稳定转述执行，没有接 LLM 即兴生成，避免测试阶段输出不可控。
