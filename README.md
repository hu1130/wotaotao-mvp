# 我淘淘最小 MVP

当前业务实现仍是 `04_内容审核模块_研发要求.pdf` 的最小可运行版本：
运营待审核队列、审核详情、通过、驳回、商家可见驳回原因、追加式审核记录、
状态/版本门禁和角色权限检查。其他业务模块尚未实现。

`packages/contracts` 已提供模块 01-08 的最小共享 TypeScript 契约和可执行接口
清单，供各模块并行开发和接入 `integration`。完整依赖、状态、Mock 边界、
验收清单和 PR 规则见
[`docs/MVP_INTEGRATION_CONTRACT.md`](docs/MVP_INTEGRATION_CONTRACT.md)。

## 全平台集成契约 V1

`integration/full-platform-contracts-v1` 在旧 MVP 契约之外新增了可执行的
SYS-01～SYS-08 集成边界：95 个 HTTP 接口、69 个事件/异步命令、OpenAPI 3.1、
AsyncAPI 3、独立事件 JSON Schema、统一 Topic/错误码/幂等注册表、固定 Fixture、
生成式 TypeScript SDK 和契约驱动 Mock（默认 `4011`）。这套产物用于多人并行开发和
持续集成；它不表示 8 个系统的真实业务实现已经全部完成。

主要入口：

- [契约治理与兼容规则](docs/CONTRACT_GOVERNANCE.md)
- [集成分支、环境和版本升级顺序](docs/INTEGRATION_BRANCH_AND_RELEASE.md)
- [WBS 0.1～10.3 逐任务 DoR/DoD](docs/INTEGRATION_TASKS.md)
- [统一 Topic 注册说明](docs/TOPIC_REGISTRY.md)
- [本地 Dev 环境](infra/dev/README.md)

```bash
pnpm contracts:generate
pnpm sdk:generate
pnpm contracts:test:provider
pnpm contracts:test:consumer
pnpm contracts:breaking
pnpm dev:contracts
```

机器可读入口位于 `packages/contracts/platform/`；SDK 位于
`packages/platform-sdk/`；Mock 位于 `apps/platform-contract-mock/`。契约、SDK、
Provider/Consumer 测试、破坏性变更、类型检查和构建门禁由
`.github/workflows/contracts.yml` 强制执行。

## 技术栈

- 前端：React 19、Vite、TypeScript
- 后端：Fastify、TypeScript
- 数据库：SQLite、Prisma
- 测试：Vitest、Fastify inject

`apps/web` 是运营审核界面，`apps/api` 是审核模块 API，`packages/contracts`
保存共享类型、接口清单、生成后的 OpenAPI 和最小契约校验器。
`apps/mock-api` 从 OpenAPI 读取路由、权限、ID 前缀和状态约定，供未完成模块联调。

## 本地启动

需要 Node.js 20+ 和 pnpm。

```bash
pnpm install
pnpm db:setup
pnpm dev
```

打开 `http://localhost:5174`。API 默认监听 `http://localhost:3001`。

模拟运营身份由前端通过开发请求头传递：

```text
x-role: OPERATOR
x-user-id: op_chen_001
x-user-name: 陈晨（URL 编码）
```

这只是 MVP 的身份上下文适配层；接入正式身份服务时，应由可信网关或认证中间件写入请求上下文，不能信任公网客户端自行提供的角色请求头。

## 测试与构建

```bash
pnpm typecheck
pnpm test
pnpm build
```

测试先校验 TypeScript manifest 与 OpenAPI 一致性，再运行契约驱动 Mock 和
模块 04 接口测试。模块 04 测试会重建独立的 `test.db`，不会修改本地演示数据库。

修改公共契约后重新生成并校验 OpenAPI：

```bash
pnpm openapi:generate
pnpm openapi:check
```

## API

```text
GET  /reviews/pending
GET  /reviews/:contentId
POST /reviews/:contentId/approve
POST /reviews/:contentId/reject
GET  /contents/:contentId/review-history
```

审核请求必须携带当前 `contentVersion`。后端用 `contentId + contentVersion + PENDING_REVIEW` 条件更新状态，并通过审核记录唯一约束保证同一版本只有一个审核结果。

`requireApprovedContent(contentId)` 是发布模块必须调用的后端门禁。当前仓库没有实现发布业务；所有非 `APPROVED` 内容都会得到稳定错误 `CONTENT_NOT_APPROVED`。

## 范围边界

没有实现 AI 生成、自动发布、授权账号、账号匹配、收益、申诉或完整风控。上游商品和内容数据仅通过固定种子数据模拟，以便独立验收审核模块。
