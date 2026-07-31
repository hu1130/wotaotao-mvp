# @wotao/contracts

模块 01-08 共用的最小 TypeScript 契约。它提供：

- 共享 ID、角色、渠道、状态、错误、分页和响应信封；
- 商品、内容、审核、发布、公开页和询盘的输入输出类型；
- `MvpApiOperationMap` 编译期 operation 输入输出映射；
- `MVP_API_CONTRACTS` 和 `MVP_MODULES` 运行时清单；
- 最小响应、分页、UTC 时间和接口清单校验器。

完整业务语义、Mock 边界、验收清单和 PR 规则见
[`docs/MVP_INTEGRATION_CONTRACT.md`](../../docs/MVP_INTEGRATION_CONTRACT.md)。

## 使用

```ts
import type {
  MvpApiRequest,
  MvpApiResponse,
} from "@wotao/contracts";

type CreatePublicationRequest = MvpApiRequest<"publishing.create">;
type CreatePublicationResponse = MvpApiResponse<"publishing.create">;
```

接口测试应复用运行时信封校验：

```ts
import {
  isErrorResponse,
  isPage,
  isSuccessResponse,
} from "@wotao/contracts";
```

## 校验

```bash
pnpm --filter @wotao/contracts typecheck
pnpm --filter @wotao/contracts test
```

契约变更必须同时更新类型、`MVP_API_CONTRACTS`、集成文档和契约测试。
