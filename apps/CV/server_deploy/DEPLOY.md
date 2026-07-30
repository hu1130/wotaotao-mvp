# Linux 服务端与客户端部署

本文档用于把项目拆成两部分部署：

- 服务端：Docker Compose 运行 MySQL、PostgreSQL + pgvector、Redis、FastAPI、avatar。
- 客户端：前台设备运行摄像头、人脸识别、手势、本地音频和现场交互。

客户端支持 API-only 模式：前台设备只访问 FastAPI/avatar，不需要直连 MySQL/PostgreSQL/Redis。

公共 Python 模块位于仓库根目录 `shared_runtime/`。Compose 通过独立的
`additional_contexts` 将共享层交给 Docker，不能再单独复制 `server_deploy/` 作为完整源码。

## 一、服务端部署

### 1. 服务器准备

已确认服务器可用 Docker：

```bash
docker --version
docker compose version
```

阿里云安全组至少放行：

```text
80    Nginx 统一入口
```

调试阶段也可以临时放行 `8000/3456`，正式使用建议只保留 `80`，由 Nginx 转发到内部服务。数据库端口不建议开放到公网。当前完整 Compose 内部使用容器网络访问数据库。

旧版客户端如果仍要直连数据库，需要在 `.env.server` 中把：

```env
DB_BIND_ADDRESS=127.0.0.1
```

改成服务器内网 IP 或 `0.0.0.0`，并在阿里云安全组只允许客户端 IP 访问 `3306/5432/6379`。Redis 如果要对外暴露，建议配置 `REDIS_PASSWORD`。

### 2. 上传部署包

在本地生成包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\materialize-runtime.ps1 `
  -Role server `
  -Destination D:\CV_deploy\server_deploy_bundle `
  -Force `
  -IncludeEnvironment
tar.exe -czf .\server_deploy.tar.gz -C D:\CV_deploy\server_deploy_bundle .
```

上传到服务器：

```powershell
scp .\server_deploy.tar.gz root@服务器IP:/opt/
```

服务器解压：

```bash
cd /opt
mkdir -p cv_deploy_new
tar -xzf server_deploy.tar.gz -C cv_deploy_new
cp -a server_deploy server_deploy_backup_$(date +%Y%m%d_%H%M%S)
python3 cv_deploy_new/server_deploy/scripts/sync-runtime-tree.py \
  cv_deploy_new/server_deploy /opt/server_deploy \
  --preserve cache --preserve avatar/cache --preserve employees --preserve knowledge_base
python3 cv_deploy_new/server_deploy/scripts/sync-runtime-tree.py \
  cv_deploy_new/shared_runtime /opt/shared_runtime
cd server_deploy
```

### 3. 配置环境

```bash
cp .env.server.example .env.server
vi .env.server
```

必须修改：

```env
API_KEY=换成强随机字符串
API_SECRET=换成强随机字符串
MYSQL_PASSWORD=换成强密码
PG_PASSWORD=换成强密码
```

默认租户继续使用上面的 `API_KEY/API_SECRET`。新增租户必须分配独立凭证，并让该租户前台的 `TENANT_ID` 与凭证映射一致：

```env
TENANT_ID=default
TENANT_API_CREDENTIALS_JSON={"tenant-a-key":{"tenant_id":"tenant-a","secret":"独立强密钥"}}
VOICE_TICKET_TTL_SECONDS=60
```

上面的租户 HMAC 仅保留给管理端和旧客户端。新 Windows 前台使用一次性设备激活：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python tools/device_admin.py create-activation --tenant-id tenant-a --label "客户A前台"
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python tools/device_admin.py list-devices --tenant-id tenant-a
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python tools/device_admin.py revoke-device --device-id dev_xxx
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python tools/device_admin.py purge-tenant-devices --tenant-id tenant-a --confirm tenant-a
```

客户端首次启动生成 Ed25519 私钥，服务端只保存公钥并分配 `tenant_id/device_id`。每个请求带 timestamp、nonce 和设备签名；nonce 由 Redis 原子去重。数字人页面通过一次性 bootstrap 换取 HttpOnly 租户会话；客户端 Python 通过设备签名申请短期 avatar 状态会话。数字人页面、对话、语音票据、状态接口和 WebSocket 都不允许匿名回退 `default`，语音锁和 ready 状态按租户与设备隔离。

服务端不信任请求 body/query 中的 `tenant_id`；REST 租户来自 HMAC API key，浏览器语音 WebSocket 使用 `/api/v1/dialog/voice-ticket` 签发的一次性 Redis 票据。不要为多个租户复用同一个 API key。

如果要启用知识库问答或语音对话，再配置对应供应商 key：

```env
KNOWLEDGE_EMBEDDING_API_KEY=
KNOWLEDGE_ANSWER_API_KEY=
DIALOG_CHAT_API_KEY=
VOLC_ASR_APP_KEY=
VOLC_ASR_ACCESS_KEY=
VOLC_TTS_APP_KEY=
VOLC_TTS_ACCESS_KEY=
```

### 4. 启动服务

```bash
chmod +x scripts/*.sh
./scripts/start-server.sh
```

也可以直接执行：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d --build
```

人物长期记忆由独立 `memory-worker` 消费 PostgreSQL outbox。API 镜像更新后应确保两者使用同一镜像版本：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml build api
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api memory-worker
# 等待 `docker compose ... ps api` 显示 healthy 后再刷新常驻 Nginx 的 upstream DNS
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
curl -fsS http://127.0.0.1/health
```

### 5. 健康检查

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml ps
docker compose --env-file .env.server -f docker-compose.deploy.yml ps api memory-worker postgres
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3456/healthz
```

浏览器访问：

```text
http://服务器IP/
http://服务器IP/control.html
```

`/avatar-ready`、`/dialog-audio-lock` 和 `/dialog-settings` 是设备会话保护接口，不能再用匿名 curl 作为健康检查；容器与运维健康检查统一使用公开的 `/healthz`。

### 6. 日志

```bash
./scripts/logs-server.sh
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f api avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f api memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f mysql postgres redis
```

运行数据：

```text
Docker volumes: mysql_data, postgres_data, redis_data
项目目录: cache/, avatar/cache/, employees/, knowledge_base/
```

### 7. 知识库索引

把文档放入服务端：

```text
/opt/server_deploy/knowledge_base/
```

非默认租户必须放入独立目录：

```text
/opt/server_deploy/knowledge_base/tenants/<tenant_id>/
```

容器内对应路径固定为：

```text
/app/knowledge_base
```

不要在服务端 `.env.server` 里使用 Windows 路径，例如 `D:\CV\knowledge_base`。

## 创建企业控制台管理员

每个客户使用同一控制台入口 `/control-login.html`，登录凭据由 `租户 ID + 用户名 + 密码` 组成。创建客户管理员：

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api \
  python tools/tenant_admin.py create \
  --tenant-id tenant-a \
  --tenant-name "客户 A" \
  --username admin \
  --display-name "企业管理员"
```

创建命令输出的初始密码只显示一次。需要换密码时执行：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api \
  python tools/tenant_admin.py reset-password --tenant-id tenant-a --username admin
```

企业管理员只能看到本租户员工、人脸向量、设备、采集任务和知识库。企业文档通过控制台上传到 `/app/knowledge_base/tenants/<tenant_id>/managed/`，上传完成后在控制台重建索引。

然后在 avatar 控制台触发索引，或调用 API：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/index
```

受保护 API 需要签名。推荐优先使用 avatar 控制台或项目工具调用。

### 8. 停止服务

```bash
./scripts/stop-server.sh
```

停止不会删除数据库卷。要清空数据库，需要显式删除 Docker volumes，谨慎操作。

## 二、客户端部署

### 1. 硬件要求

客户端设备需要：

- 摄像头
- 浏览器或可访问服务端 avatar 页面的大屏
- 可选 GPU
- 可选麦克风/扬声器
- 能访问服务端 `8000` 和 `3456`

API-only 客户端只需要访问服务端 `80`。不要开放数据库端口。

### 2. 上传或解压客户端包

```powershell
scp .\dist_deploy\client_deploy.tar.gz user@客户端机器:/path/
```

Linux 客户端：

```bash
tar -xzf client_deploy.tar.gz
cd client_deploy
cp .env.client.example .env
```

Windows 客户端解压后，把 `.env.client.example` 复制为 `.env`。

### 3. 配置客户端

API-only 客户端的 `.env` 是最小配置，不包含数据库密码、LLM key 或供应商密钥。修改 `.env`：

```env
API_KEY=与服务端一致
API_SECRET=与服务端一致
API_BASE_URL=http://服务器IP:8000
AVATAR_SERVER_URL=http://服务器IP:3456
CLIENT_API_ONLY=1

MYSQL_HOST=服务器IP
MYSQL_PASSWORD=与服务端一致
PG_HOST=服务器IP
PG_PASSWORD=与服务端一致
REDIS_HOST=服务器IP

CAMERA_INDEX=0
ENABLE_GUI=0
USE_GPU=0
```

### 4. 启动客户端

Windows：

```powershell
.\scripts\start-client.ps1
```

生成 Windows 一键客户端 EXE：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-client-exe.ps1 -ServerBaseUrl http://服务器IP
```

输出目录：

```text
dist_client_exe\dist\CVClient\CVClient.exe
```

分发给现场设备时只发 `CVClient` 整个目录。目录内 `.env` 是 API-only 最小配置，不包含数据库密码和供应商密钥。

Linux：

```bash
chmod +x scripts/start-client.sh
./scripts/start-client.sh
```

pip 安装命令已统一使用清华源：

```text
-i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 并发容量与运行域隔离

识别请求中的 `tenant_id + device_id` 会被规范化为稳定运行域。多帧投票、识别缓存、轨迹追溯、陌生人/已签到在场状态、人物会话和调试日志节流都按运行域隔离；相同 `track_id` 在不同设备或租户之间不会互相覆盖或清理。旧客户端不传 `tenant_id` 时自动进入 `default` 租户。

当前容量参数：

- `API_THREADPOOL_TOKENS`：同步数据库、识别和模型适配器可使用的线程令牌。
- `RECOGNITION_MAX_CONCURRENCY` / `RECOGNITION_QUEUE_TIMEOUT_SECONDS`：识别入口的有界并发和排队上限，过载时返回 HTTP 429。
- `VOICE_MAX_CONCURRENCY` / `VOICE_QUEUE_TIMEOUT_SECONDS`：语音 WebSocket 容量，过载时返回 `voice_capacity_exceeded` 并以 1013 关闭。
- `RUNTIME_SCOPE_*`：分片锁数量、空闲运行域回收时间和最大运行域数量。
- `MYSQL_POOL_SIZE`、`PG_POOL_SIZE`、`REDIS_POOL_SIZE`：数据库连接容量；必须结合数据库 `max_connections` 和实际设备数调整。

`GET /api/v1/runtime/capacity`（HMAC 签名）可查看识别/语音当前 active、accepted、rejected 和平均等待时间。

`API_WORKERS` 当前必须为 `1`。这是显式安全约束：人物会话和短时轨迹仍是进程内低延迟状态，直接启用多 Uvicorn worker 会让同一设备的识别 HTTP 与语音 WebSocket 落到不同进程。现阶段通过线程池、NumPy 释放 GIL 后的矩阵计算、分片锁和有界入口并行处理不同设备；未来横向扩容时，应先把会话状态外置到 Redis，并按签名凭证绑定可信 `tenant_id`，再解除多进程保护。

当前 `tenant_id` 同时是运行时命名空间和鉴权边界：HMAC 凭证、设备签名、租户管理员会话、avatar 会话都会解析出可信租户，员工、考勤、知识库、人物记忆和人脸向量查询均必须带租户条件。后续增加新表、新缓存或新入口时仍需逐项执行同样约束，不能信任 body/query 自报租户。

## 三、常见问题

### Docker build 下载依赖慢

Dockerfile 已设置：

```text
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

Node 依赖仍走 npm 默认源。如服务器访问 npm 慢，可临时设置 npm registry 后再构建。

### PostgreSQL 报 vector 扩展错误

服务端使用 `pgvector/pgvector:pg16` 镜像，正常包含 vector 扩展。如果仍失败，查看：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml logs postgres
docker compose --env-file .env.server -f docker-compose.deploy.yml logs api
```

### API 启动失败

重点检查：

- `.env.server` 中 MySQL/PostgreSQL 密码是否一致
- `mysql/postgres/redis` health 是否 healthy
- `API_KEY` 和 `API_SECRET` 是否为空或配置错误

### avatar 页面能打开但接口失败

检查 avatar 容器内 `API_BASE_URL=http://api:8000`，以及 API 是否 healthy：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f api
```

### 客户端打不开摄像头

检查：

- `CAMERA_INDEX`
- 是否有其他程序占用摄像头
- Windows 权限或 Linux `/dev/video*` 权限
- Docker 客户端模式不推荐用于 Windows 摄像头直通，优先宿主机 Python 运行

## 四、推荐提交信息

```bash
git commit -m "部署：新增服务端 Docker Compose 与客户端部署包"
```
