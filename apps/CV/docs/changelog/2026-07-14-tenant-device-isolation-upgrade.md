# 租户与设备隔离安全修复升级说明

## 1. 文档信息

- 发布日期：2026-07-14
- 对应提交：`60a86b4 fix: enforce device-scoped tenant isolation`
- 适用范围：FastAPI、Node avatar、memory-worker、Windows CVClient
- 升级性质：高风险安全问题修复，服务端与客户端需要配套升级
- 数据迁移：无数据库结构迁移，无需重启 MySQL、PostgreSQL 或 Redis
- 环境变量：本次升级没有新增或修改环境变量

## 2. 修复背景

升级前存在三类高风险问题：

1. 部分 avatar HTTP 接口和 WebSocket 在缺少有效设备会话时可能回退到服务端的 `default` 租户或默认设备，使匿名请求进入数字人业务链路。
2. `dialog-audio-lock` 和 `avatar-ready` 使用 Node 进程级全局状态，多租户或同租户多前台同时运行时可能互相影响语音仲裁与数字人模型状态。
3. 员工姓名和照片目录缺少完整的跨平台路径约束，服务端本地录入允许访问全局上传目录；default 租户的旧路径兼容删除逻辑还可能碰撞同名租户目录。

本次升级将身份、状态和文件系统三条链路统一收紧为可信的租户与设备边界。

## 3. 修复内容

### 3.1 Avatar HTTP 与 WebSocket 强制认证

- 数字人首页 `/` 和 `/index.html` 必须持有有效的 HttpOnly avatar 设备会话。
- `/dialog/chat`、`/dialog-settings`、`/voice-ticket`、TTS 接口和 `/client-log` 不再允许匿名访问。
- Node 转发对话请求时只使用 avatar session，不再使用全局 HMAC 回退到 `default`。
- Avatar WebSocket 必须先解析出有效的设备会话，control WebSocket 必须先解析出有效的租户管理员会话。
- WebSocket 注册角色必须为 `avatar` 或 `control`，未认证、未注册或角色与凭证不匹配的连接会以策略错误关闭。
- 新增公开健康接口 `GET /healthz`。健康检查不再使用受保护的 `/avatar-ready`。

正常打开数字人页面的入口仍然是 CVClient。客户端先用设备签名向 API 申请一次性 bootstrap，浏览器消费 bootstrap 后取得 HttpOnly 会话。直接在新浏览器中输入服务器首页地址不会自动获得租户身份，返回 `401` 属于预期行为。

### 3.2 数字人状态按租户和设备隔离

- `dialog-audio-lock` 和 `avatar-ready` 改为 `tenant_id + device_id` 双维度状态。
- 同一企业的两台前台设备不再共享语音锁和数字人 ready/model 状态。
- 浏览器通过 HttpOnly avatar session 访问状态接口。
- Windows 客户端 Python 进程使用 Ed25519 设备签名调用：

  ```text
  POST /api/v1/device-sessions/avatar-state-session
  ```

  API 返回短期 avatar session，客户端随后通过 `X-Avatar-Session` 访问 Node 状态接口。
- 状态会话会验证设备仍处于 active 状态；设备被撤销后不能继续刷新会话。
- 旧 HMAC 只保留给服务端 legacy 运行模式，并且只能绑定服务端配置中的固定租户和设备，不能由请求自行声明租户。

### 3.3 员工姓名与照片路径安全

- 新增共享员工姓名规范化模块，统一用于服务端、客户端、控制台录入、拍照工具和 pgvector 删除链路。
- 拒绝以下姓名：

  - 空姓名、`.`、`..`；
  - 包含 `/`、`\`、Windows 非法路径字符或控制字符；
  - 以点或空格结尾；
  - `CON`、`NUL`、`COM1`、`LPT1` 等 Windows 保留名；
  - 超过 120 个字符的姓名。

- 员工照片目录只能通过安全函数生成：

  ```text
  employees/<tenant_id>/<employee_name>/
  ```

- 服务端本地录入只允许读取当前租户的以下目录：

  ```text
  uploads/<tenant_id>/
  captures/<tenant_id>/
  employees/<tenant_id>/
  ```

- 删除员工时只删除当前租户的员工目录，已移除 default 租户的旧全局目录兼容删除逻辑。
- 本地照片重建 pgvector 时只扫描当前 `TENANT_ID` 对应的员工目录，并在写入向量时显式传递租户。

## 4. 兼容性影响

| 场景 | 升级后的行为 | 操作要求 |
|---|---|---|
| 已激活的新 CVClient | 自动申请 bootstrap 和状态会话 | 无需重新激活 |
| 升级前的旧 CVClient | 人脸识别仍可能工作，但 Python 状态请求会收到 `401`，语音锁和模型音色状态可能退化 | 必须替换为本次重新打包的完整客户端目录 |
| 直接访问服务器首页 | 没有设备会话时返回 `401` | 从 CVClient 启动数字人页面 |
| 浏览器保存了过期 cookie | 页面或状态接口返回 `401` | 关闭页面后从 CVClient 重新打开 |
| 控制台 WebSocket | 必须具有有效的租户管理员 cookie | 重新登录对应租户控制台 |
| 多台前台设备 | 各自维护语音锁和 ready 状态 | 不需要额外配置 |

设备私钥和激活身份位于：

```text
%LOCALAPPDATA%\CVClient\device-identity.json
```

替换程序目录不会删除该文件，因此同一台电脑升级客户端时不需要重新输入激活码。

## 5. 升级前检查

1. 确认服务器部署目录为 `/opt/server_deploy`，共享运行时为 `/opt/shared_runtime`。
2. 备份当前部署源码或记录当前镜像 ID，便于需要时整体回滚。
3. 确认数据库和缓存容器健康：

   ```bash
   cd /opt/server_deploy
   docker compose --env-file .env.server -f docker-compose.deploy.yml ps
   ```

4. 告知正在使用旧客户端的前台：服务端切换后应尽快替换新客户端。
5. 不需要停止或重建 MySQL、PostgreSQL、Redis。

## 6. 服务器升级步骤

将本次提交涉及的 `server_deploy/` 与 `shared_runtime/` 文件按原目录结构同步到服务器。不要覆盖服务器现有 `.env.server`。

进入服务器后执行：

```bash
cd /opt/server_deploy

docker compose --env-file .env.server -f docker-compose.deploy.yml config --quiet
docker compose --env-file .env.server -f docker-compose.deploy.yml build api avatar

docker compose --env-file .env.server -f docker-compose.deploy.yml \
  up -d --no-deps api avatar memory-worker
```

等待 API 与 avatar 健康后，再重启 Nginx，使其重新解析容器地址：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml ps api avatar memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
```

禁止在 API 或 avatar 仍处于 `starting` 时开始业务验证。

## 7. 客户端升级步骤

本次已重新生成客户端：

```text
D:\CV_deploy\dist_client_exe\dist\CVClient\
```

生成时间：2026-07-14 14:20:32。

升级客户电脑时：

1. 完全退出旧 `CVClient.exe`，并关闭它打开的数字人浏览器窗口。
2. 备份旧程序目录中的业务自定义文件；不要把旧 EXE 与新 `_internal` 目录混用。
3. 将新的整个 `CVClient` 文件夹复制到客户电脑。
4. 启动新 `CVClient.exe`。
5. 已激活设备应直接加载原 DPAPI 身份；如果提示服务器不匹配或身份文件损坏，再按设备迁移流程处理，不要直接复制其他电脑的身份文件。

交付时必须复制完整文件夹，不能只复制 `CVClient.exe`。

## 8. 升级后验证

### 8.1 容器与公开健康接口

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml ps
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/healthz
```

预期：API、avatar、Nginx 为 healthy，memory-worker 为 running；两个健康接口均返回 `ok: true`。

### 8.2 匿名访问拒绝

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/dialog-settings
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/avatar-ready
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1/voice-ticket
```

预期：以上请求全部返回 `401`。

### 8.3 客户端和 WebSocket

1. 从两台已激活设备分别启动 CVClient。
2. 页面应正常加载，日志中出现对应的可信租户和设备：

   ```text
   WebSocket 身份候选已解析: avatar_tenant=<tenant_id>
   WebSocket 租户身份已锁定: role=avatar tenant=<tenant_id>
   ```

3. 对应租户控制台登录后，control WebSocket 日志中的 tenant 必须等于登录租户。
4. 不允许出现 `role=avatar tenant=default`，除非该设备真实绑定的租户就是 `default`。

### 8.4 状态隔离

至少使用两个不同设备会话验证：

- 设备 A 写入的临时语音锁 owner 不出现在设备 B；
- 设备 A 设置的临时 avatar model 不出现在设备 B；
- `/dialog-settings` 返回的 `tenantId/deviceId` 与每个会话自身绑定一致。

不要断言其他设备必须完全处于 unlocked 状态，因为正在工作的设备可能合法持有自己的 `local_dialog` 或 `legacy_tts` 锁。应比较指定测试 owner 是否发生串线。

### 8.5 关键日志

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml \
  logs --since=15m api avatar memory-worker
```

确认没有 `Traceback`、`Unhandled`、`ReferenceError`、`TypeError` 或 `CRITICAL`。

## 9. 本次验证结果

2026-07-14 已完成：

- 本地 Node 测试 8 项通过；
- 本地 Python 定向测试 16 项通过；
- 服务器 avatar 容器 Node 测试 8 项通过；
- 服务器 API 容器 Python 定向测试 16 项通过；
- 共享运行时边界检查通过；
- API、avatar、Nginx healthy，memory-worker running；
- `/`、`/dialog-settings`、`/avatar-ready`、`/voice-ticket` 匿名请求均返回 `401`；
- 两台 `default` 设备与一台 `computer-mine` 设备完成真实状态隔离验证；
- 现有 avatar/control WebSocket 均按凭证绑定的租户成功重新连接；
- 15 分钟运行日志未发现关键运行时错误。

完整的测试发现模式包含长期运行用例，未在本次执行窗口内结束，因此不记为“全量测试通过”；上述结果是针对本次修复链路及相关既有运行域的定向回归。

## 10. 回滚说明

该升级的服务端与客户端协议是配套的。若必须回滚，应同时回滚以下内容：

- API 镜像与设备状态会话路由；
- avatar 镜像与 Node 鉴权/状态存储；
- Windows CVClient 完整程序目录。

只回滚服务端或只回滚客户端，可能导致状态会话申请失败、数字人状态无法读取或语音锁失效。

推荐回滚方式：

1. 使用升级前保存的完整源码快照和镜像，不要在有其他 Agent 未提交改动的工作区执行破坏性 Git 重置。
2. 恢复配套的 API/avatar 镜像与旧客户端目录。
3. 重新创建对应容器后等待健康，再重启 Nginx。
4. 重新执行健康检查、客户端页面和语音链路验证。

回滚会重新引入本次修复的安全风险，只应用于紧急恢复，并应尽快重新升级。

## 11. 后续开发约束

- 新增 avatar 业务接口时，必须明确使用 avatar device session、tenant admin session 或内部 HMAC，禁止匿名继承默认租户。
- 设备短时状态的 key 至少包含 `tenant_id + device_id`。
- 新增员工文件操作时必须复用共享姓名和租户路径模块，禁止自行拼接 `EMPLOYEES_DIR/name`。
- 健康检查使用 `/healthz`，不得为了探活重新开放 `/avatar-ready` 或 `/dialog-settings`。
- 新客户端不得内置长期 `API_KEY/API_SECRET`，继续使用设备 Ed25519 身份和短期会话。
