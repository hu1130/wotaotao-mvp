# Linux 服务端与客户端部署

本文档用于把项目拆成两部分部署：

- 服务端：Docker Compose 运行 MySQL、PostgreSQL + pgvector、Redis、FastAPI、avatar。
- 客户端：前台设备运行摄像头、人脸识别、手势、本地音频和现场交互。

客户端支持 API-only 模式：前台设备只访问 FastAPI/avatar，不需要直连 MySQL/PostgreSQL/Redis。

公共 Python 模块位于仓库根目录 `shared_runtime/`。客户端 EXE 构建脚本会先把共享层
与 `client_deploy/` 角色层合并到临时源码目录，再交给 PyInstaller，禁止手工复制共享模块。

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

新安装包不再分发租户 `API_KEY/API_SECRET`。管理员先在服务器 API 容器执行 `docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python tools/device_admin.py create-activation --tenant-id <tenant>`，客户首次启动时输入一次性激活码；客户端自动生成 Ed25519 身份，云端返回可信 `TENANT_ID/DEVICE_ID`。私钥由 Windows DPAPI 保护在 `%LOCALAPPDATA%\CVClient\device-identity.json`，不得复制到其他机器。旧 HMAC 配置仅用于兼容既有安装。

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

### 5. 健康检查

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3456/healthz
```

浏览器访问：

```text
http://服务器IP/
http://服务器IP/control.html
```

`/avatar-ready`、`/dialog-audio-lock` 和 `/dialog-settings` 是设备会话保护接口，不能再用匿名 curl 作为健康检查；健康检查统一使用公开的 `/healthz`。

### 6. 日志

```bash
./scripts/logs-server.sh
docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f api avatar
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

容器内对应路径固定为：

```text
/app/knowledge_base
```

不要在服务端 `.env.server` 里使用 Windows 路径，例如 `D:\CV\knowledge_base`。

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
API_KEY=
API_SECRET=
API_BASE_URL=http://服务器IP:8000
AVATAR_SERVER_URL=http://服务器IP:3456
CLIENT_API_ONLY=1
CLIENT_DEVICE_ENROLLMENT=auto
CLIENT_ACTIVATION_CODE=

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
