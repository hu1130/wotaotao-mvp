# Agent1 交付：修复“看到我说 are you ok”未创建到场任务

## 问题现象

用户说了类似“以后看到我主动说 are you ok”的要求，离开后再次出现没有自动播报。

## 日志结论

服务器日志显示真实 ASR 文本为：

- `以后见到我要跟我说， are you？ OK？`
- `我说以后看到我，我一定要说 are you OK？`

这两句之后日志进入了普通对话和 RAG：

- `语音动作分流: 未命中工具动作，进入普通对话`
- `Omni RAG 意图路由`

没有出现 `人物到场任务已写入`，说明当时没有创建 `person_arrival_tasks` 任务；后续重新入场检测虽然正常发生，但没有 active 任务可领取，所以不会播报。

## 根因

旧解析器只覆盖了：

- `以后我一过来...`
- `我回来/我出现/我到这里...`

没有覆盖 ASR 常见表达：

- `以后看到我...`
- `以后见到我...`
- `我说以后看到我...`
- `记住以后看到我...`

同时 `记住以后看到我...` 会先被普通 `remember` 规则吃掉，无法进入到场任务规则。

## 修复方案

1. 扩展自己到场任务解析，支持 `看到我/看见我/见到我/碰到我/遇到我`。
2. 兼容 ASR 口语前缀 `我说...`。
3. 兼容 ASR 把 `你就说` 识别成 `我一定要说` 的场景。
4. 对 `记住...` 内容先尝试到场任务解析，命中时优先返回 `arrival_task`；普通“记住我喜欢...”仍保持个人记忆。
5. 对非引号短英文内容做轻量规范化，把 `are you？ OK？` 变成 `are you OK`，避免固定播报断句奇怪。

## 修改文件

- `server_deploy/core/person_memory/commands.py`
- `server_deploy/tests/test_person_memory.py`

## 额外数据修复

由于用户这句是在修复前说的，当时没有写入任务。本次已通过现有服务接口为当前用户补写重复到场任务：

```text
tenant=computer-mine
target=小游
content=are you OK
exactText=true
repeat=true
taskId=ea2c085a-f67a-4e99-af55-41a4a937a246
```

## 验证

本地：

```powershell
$env:PYTHONPATH='server_deploy'
python -m unittest server_deploy.tests.test_person_memory -v
python -m py_compile server_deploy\core\person_memory\commands.py server_deploy\tests\test_person_memory.py
```

结果：`test_person_memory` 12 条通过，编译通过。

服务器：

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml build api
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python -m unittest tests.test_person_memory -v
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/healthz
```

结果：

- API healthy。
- avatar healthy。
- nginx healthy。
- 服务器 `test_person_memory` 12 条通过。
- 真实 ASR 样本现在解析为 `arrival_task`。

## Agent2 复测建议

1. 说“以后看到我要跟我说 are you ok”，确认日志出现 `人物到场任务已写入`。
2. 用户离开 1-2 秒后回来，确认日志出现 `人物到场任务已触发` 和 `event_type=arrival_task`。
3. 确认普通“记住我喜欢喝冰美式”仍进入 `remember`，不会误变成到场任务。
