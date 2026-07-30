# T0 公共契约与模拟服务

本模块交付 MVP 的共享对象、状态枚举、OpenAPI、权限矩阵、状态流转和固定数据模拟 API。它不实现商品、内容、发布或询盘的生产业务逻辑，也不修改现有审核模块实现。

## 目录

```text
packages/contracts/openapi.json   MVP OpenAPI 3.1 契约
packages/contracts/src/index.ts   前后端共享 TypeScript 类型
packages/contracts/src/runtime.mjs
                                  模拟服务使用的运行时枚举和状态流转
apps/mock-api/                    独立模拟 API
docs/permissions.md               接口权限矩阵
docs/state-transitions.md         状态流转规则
scripts/validate-contract.mjs     契约一致性检查
```

现有审核模块的类型和接口语义得到保留，包括 `contentVersion` 并发门禁、结构化驳回原因和 `ReviewDecisionResult`。

## 运行

需要 Node.js 20+ 和 pnpm：

```bash
pnpm install
pnpm --filter @wotao/contracts check:openapi
pnpm --filter @wotao/contracts typecheck
pnpm --filter @wotao/mock-api test
pnpm --filter @wotao/mock-api start
```

模拟服务默认监听 `http://127.0.0.1:4010`，可使用 `HOST` 和 `PORT` 覆盖。

## 请求上下文

- 后台接口使用 `x-role: MERCHANT | OPERATOR | BUYER`。
- 商家请求必须同时使用 `x-merchant-id`。
- 运营审核兼容现有模块的 `x-user-id`、`x-user-name`。
- 创建发布必须使用至少 8 个字符的 `idempotency-key`。
- 模拟回调签名为 `x-callback-signature: mock-valid-signature`。

## 固定数据

| 对象 | ID | 用途 |
| --- | --- | --- |
| 演示商家 | `merchant_demo` | 正常业务路径 |
| 其他商家 | `merchant_other` | 越权隔离测试 |
| 公开商品 | `product_demo_001` | 内容生成和公开浏览 |
| 已生成内容 | `content_demo_generated` | 提交审核、发布门禁 |
| 待审核内容 | `content_demo_pending` | 运营审核 |
| 已通过内容 | `content_demo_approved` | 创建发布 |
| 抖音账号 | `account_douyin_demo` | 抖音模拟发布 |
| 小红书账号 | `account_xhs_demo` | 小红书模拟发布 |
| 成功发布 | `publication_demo_success` | feed 和询盘归因 |
| 处理中发布 | `publication_demo_processing` | 回调测试 |
| 失败发布 | `publication_demo_failed` | 人工重试 |
| 新询盘 | `inquiry_demo_001` | 状态更新 |

创建发布时使用 `scenario: SUCCESS | PROCESSING | FAILURE` 切换结果。相同 `idempotency-key` 和相同请求返回原发布记录；同一键对应不同请求时返回冲突。

## 契约变更

1. 修改 `packages/contracts/openapi.json` 和受影响的共享类型。
2. 说明调用方、数据库及前端影响，并由技术负责人确认。
3. 运行契约检查、类型检查和模拟 API 测试。
4. 通知依赖该契约的模块负责人。

## 当前限制

真实抖音/小红书联调仍需要现有发布系统的接口地址、鉴权字段、账号字段和回调验签规则。模拟服务为内存实现，重启后新增数据重置，仅用于模块并行开发和联调。
