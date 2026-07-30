# Agent1 交付：抑制到场任务因识别抖动反复播报

## 问题现象

用户反馈当前只要摄像头识别稍微抖动，就会反复播报 `are you OK`。

## 日志结论

服务器日志显示同一任务连续触发：

- `人物到场任务离场: missing=1.0~1.2s threshold=1.0s`
- `人物到场任务重新入场检测: absent=1.5~1.7s threshold=1.0s`
- `人物到场任务已触发: task=ea2c085a-f67a-4e99-af55-41a4a937a246 reason=reentry`

这说明人脸检测短暂丢帧或角度变化被当成真实离开，1 秒阈值太敏感；同时重复任务没有任务级冷却，导致每次抖动都能领取并播报。

## 修复方案

1. 到场任务离场阈值从 `1.0s` 调整为 `2.5s`。
   - 过滤普通丢帧和轻微转头。
   - 仍保留短暂真实离开后回来可触发。
2. 新增任务级触发冷却 `PERSON_ARRIVAL_TASK_TRIGGER_COOLDOWN_SECONDS=30.0`。
   - 同一 active 到场任务在冷却期内不会被再次领取。
   - 冷却在 PostgreSQL `claim_arrival_tasks()` 查询层生效，从源头减少 avatar 事件。
3. 触发日志增加 cooldown 秒数，便于后续排查。

## 修改文件

- `server_deploy/config/camera.py`
- `server_deploy/core/person_memory/repository.py`
- `server_deploy/core/remote_recognition.py`
- `server_deploy/.env.server`
- `server_deploy/.env.server.example`

## 验证

本地：

```powershell
python -m py_compile server_deploy\config\camera.py server_deploy\core\remote_recognition.py server_deploy\core\person_memory\repository.py
$env:PYTHONPATH='server_deploy'
python -m unittest server_deploy.tests.test_person_memory -v
```

结果：编译通过，`test_person_memory` 12 条通过。

服务器：

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml build api
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python -m py_compile config/camera.py core/remote_recognition.py core/person_memory/repository.py
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/healthz
```

服务器运行配置确认：

```text
arrival_absent 2.5
arrival_cooldown 30.0
```

结果：

- API healthy。
- avatar healthy。
- nginx healthy。
- 最近 1 分钟未再出现新的 `are you OK` / `arrival_task` 连续触发日志。

## Agent2 复测建议

1. 用户保持在画面内轻微转头、移动或光照变化，不应反复触发 `are you OK`。
2. 用户真实离开超过约 2.5 秒再回来，应触发一次到场任务。
3. 30 秒内同一任务不应重复播报；30 秒后再次真实离开回来可再次触发。
