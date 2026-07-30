# 我淘淘内容审核模块 MVP

本仓库实现 `04_内容审核模块_研发要求.pdf` 的最小可运行版本：运营待审核队列、审核详情、通过、驳回、商家可见驳回原因、追加式审核记录、状态/版本门禁和角色权限检查。

## 技术栈

- 前端：React 19、Vite、TypeScript
- 后端：Fastify、TypeScript
- 数据库：SQLite、Prisma
- 测试：Vitest、Fastify inject

`apps/web` 是运营审核界面，`apps/api` 是审核模块 API，`packages/contracts` 保存共享状态和接口类型。

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

接口测试会重建独立的 `test.db`，不会修改本地演示数据库。

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
