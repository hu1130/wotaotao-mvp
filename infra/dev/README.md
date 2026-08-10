# 全平台本地 Dev 环境

本目录只提供可丢弃的本地基础设施：PostgreSQL 16、Redis 7 和全平台 Contract Mock。它不启动真实支付、抖音、微信、外呼、出款或生产业务服务。

旧的 `apps/mock-api`/4010 只兼容内容审核 MVP。全平台联调统一使用 `apps/platform-contract-mock`/4011；不得把旧 Mock 的成功结果当成新平台契约证据。

## 前置条件

- Docker Desktop / Docker Compose v2；
- 端口 `55442`、`56379`、`4011` 未被占用，或已在本目录 `.env` 中覆盖；
- 从仓库根目录构建，以便镜像读取工作区锁文件和版本化契约 Fixture。

## 启动

在仓库根目录执行：

```powershell
Copy-Item .\infra\dev\.env.example .\infra\dev\.env
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml up -d --build
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml ps
```

健康状态全部为 `healthy` 后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:4011/healthz
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml exec postgres pg_isready -U wotao_dev -d wotao_dev
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml exec redis redis-cli ping
```

默认连接：

| 服务 | 主机地址 | 容器内地址 |
| --- | --- | --- |
| PostgreSQL | `postgresql://wotao_dev:wotao_dev_only@127.0.0.1:55442/wotao_dev` | `postgresql://wotao_dev:wotao_dev_only@postgres:5432/wotao_dev` |
| Redis | `redis://127.0.0.1:56379/0` | `redis://redis:6379/0` |
| Contract Mock | `http://127.0.0.1:4011` | `http://contract-mock:4011` |

上述账号和密码只是本地合成值，不得复制到 Staging/Prod。真实环境由秘密管理系统注入。

## 固定 Fixture

Mock 从 `packages/contracts/platform/fixtures/http/index.json` 读取版本化 HTTP 合成数据；事件 Fixture 位于同一 `platform/fixtures` 边界内。Fixture 必须满足：

- ID、时间和业务结果固定，同一提交重复启动得到相同初始状态；
- 至少包含成功、校验失败、越权、状态冲突、幂等重放和重复事件场景；
- 企业 A/B 数据用于串户反例；联系方式、订单、支付和凭证全部为虚构值；
- Fixture 变更与 OpenAPI/AsyncAPI、SDK 和契约测试同一个 PR；
- Mock 可在内存中记录当前运行的幂等结果，但容器重启后回到固定初始状态。

Provider/Consumer 测试应直接加载这些 Fixture。禁止在各模块复制一份字段近似但版本失联的 JSON。

Mock 默认返回成功 Fixture。仅在 Local/Dev 契约调试时，可使用请求头
`X-Contract-Scenario: failure` 触发该 operation 的固定主失败样例，或使用
`X-Contract-Scenario: error:<ERROR_CODE>` 精确触发已登记错误（例如
`error:VERSION_CONFLICT`）。未知或未登记场景返回 400；该请求头不得由生产
Consumer 发送，也不得在网关中透传。

## 数据卷和重建

常规停止会保留本地数据：

```powershell
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml down
```

需要从空环境验证迁移时，先确认 Compose 项目名为 `wotao-platform-dev`，再显式删除该项目的卷：

```powershell
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml down --volumes
```

这会删除本 Compose 的本地 PostgreSQL/Redis 数据，不能恢复；不会触碰迁移包中已有的 demos 数据卷。执行前应核对 `docker compose ... config --volumes` 的输出。

## 常用诊断

```powershell
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml config
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml ps
docker compose --env-file .\infra\dev\.env -f .\infra\dev\compose.yaml logs --tail 200 contract-mock
```

若 `/healthz` 失败，先检查 Mock 日志和契约/Fixture 是否可解析。不要为了让健康检查变绿而修改业务契约或返回虚假成功。

## 边界

- Compose 仅用于 Local/Dev，不是生产编排模板；
- 不挂载浏览器 Profile、真实 `.env`、生产备份或用户目录；
- 不把真实第三方响应录制进 Fixture；
- 合成数据验证通过不等于支付、退款、发布、外呼或出款真实接入完成；这些能力仍需官方沙箱/白名单证据。
