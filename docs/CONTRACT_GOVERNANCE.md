# 全平台契约治理规范

状态：V1.0（本轮冻结）  
适用范围：Core、Marketplace、Automation、数据分析及其所有调用方  
不在本轮范围：PRD 的视觉、交互和页面设计规范

## 1. 目标与强制规则

本规范把 HTTP API、领域事件、错误码、幂等键和生成 SDK 作为多人并行开发的公共边界。任何团队不得先在业务仓库实现一套私有字段，再要求其他团队适配。

以下规则是合并门禁，而不是建议：

1. `packages/contracts/platform` 是全平台机器可读契约的唯一事实源；文档和代码示例不得覆盖其语义。
2. 同一变更必须同时交付 OpenAPI、AsyncAPI/事件 JSON Schema、请求响应样例、固定 Fixture、生成 SDK 和受影响的契约测试。
3. Provider 必须证明实现符合契约，Consumer 必须证明自己只依赖已声明的字段和状态；只有 Mock 通过不代表真实 Provider 完成。
4. 已发布的契约默认只能向后兼容演进。删除、改名、收窄类型、增加必填字段或改变既有状态语义，必须走新主版本和弃用流程。
5. 密钥、Cookie、令牌、真实手机号、真实订单和真实支付数据不得进入契约、样例、Fixture、镜像或 CI 日志。

## 2. 事实源与目录

| 制品 | 规范路径 | 用途 |
| --- | --- | --- |
| HTTP 契约 | `packages/contracts/platform/openapi.json` | OpenAPI 3.1，定义路径、鉴权、请求、响应和错误 |
| 事件契约 | `packages/contracts/platform/asyncapi.json` | AsyncAPI，定义 Topic、生产者、消费者和消息引用 |
| 事件 Schema | `packages/contracts/platform/events/*.schema.json` | 可独立校验的 JSON Schema 2020-12 |
| 注册表 | `packages/contracts/platform/registry.json` | Topic、错误码、幂等作用域、Owner 和版本索引 |
| 样例 | `packages/contracts/platform/examples/` | 规范引用的成功、失败、重复和状态迁移样例 |
| 固定数据 | `packages/contracts/platform/fixtures/` | Mock、Provider、Consumer 和 E2E 共用的合成数据 |
| TypeScript SDK | `packages/platform-sdk/src/generated/` | 只由生成器写入，不手工修改 |
| 基线 | `packages/contracts/platform/baseline/<major>.<minor>.<patch>/` | 破坏性变更比较和发布审计 |

旧的 `packages/contracts/openapi.json` 与 `MVP_API_CONTRACTS` 继续服务现有内容审核 MVP；迁移完成前不得静默改变其语义。新系统统一依赖 `platform/` 契约，迁移由明确的适配层完成。旧 MVP 的 `errorCode` 信封不得继续扩散；适配层必须把它翻译为全平台 `code` 信封并补齐 `traceId`、`retryable` 和 `fieldErrors`。

若代码生成器与生成物冲突，以生成器输入和可重复生成结果为准；生成物漂移会使 CI 失败。

## 3. 命名和信封

### 3.1 HTTP

- 资源路径使用小写复数名词和 kebab-case；动作只用于无法表达为资源状态的命令。
- `operationId` 使用 `<domain>.<verb>`，一经发布不可复用。
- JSON 字段使用 camelCase；内部 ID 是不透明字符串，调用方不得解析前缀作业务判断。
- UTC 时间使用 ISO 8601 且以 `Z` 结尾；金额使用最小货币单位的整数并显式携带币种，不交换浮点金额。
- 成功统一为 `{ data, requestId, traceId }`；失败统一为 `{ code, message, retryable, requestId, traceId, fieldErrors, currentVersion?, availableActions?, commandId? }`。`fieldErrors` 无内容时仍返回空数组。
- 页码型列表使用 `page`、`pageSize` 和 `{ items, page, pageSize, total }`；稳定快照或流式列表使用 `cursor`/`nextCursor`。同一 operation 不混用两种方式，具体上限以 OpenAPI 为准。
- 多租户归属只能来自可信身份上下文或服务端关联，不接受客户端自报 `enterpriseId`/`merchantId` 作为授权依据。

### 3.2 Topic 与事件

`registry.json` 中的 `logicalTopic` 是 Topic 名的唯一事实源；Broker 物理地址统一为：

```text
wotao.{environment}.{logicalTopic}
```

例如，注册的 `logicalTopic=commerce.order.paid.v1` 在 Dev 的物理地址是 `wotao.dev.commerce.order.paid.v1`。地址环境只能是 `dev`、`test`、`staging`、`prod`；事件信封中的环境枚举对应为 `DEV`、`TEST`、`STAGING`、`PROD`。业务代码只能从 registry 和环境配置取得地址，不得自行拼写另一套 Topic 名。

所有事件使用统一信封：

```json
{
  "eventId": "evt_order_paid_001",
  "eventType": "OrderPaid",
  "schemaVersion": 1,
  "occurredAt": "2026-08-10T01:00:00Z",
  "publishedAt": "2026-08-10T01:00:01Z",
  "producer": "SYS-02",
  "environment": "DEV",
  "audience": ["SYS-03", "SYS-04", "SYS-06", "SYS-08"],
  "aggregateType": "Order",
  "aggregateId": "ord_demo_001",
  "aggregateVersion": 2,
  "enterpriseId": "ent_demo_001",
  "traceId": "trace_contract_fixture_001",
  "correlationId": "cor_demo_001",
  "causationId": "cmd_demo_001",
  "idempotencyKey": "PAYMENT_SUCCESS:pay_demo_001:txn_demo_001",
  "payload": {}
}
```

- `eventId` 是投递去重键；Consumer 必须按 `consumerName + eventId` 建唯一约束。`idempotencyKey` 是业务唯一键，执行副作用前还要按 registry 的业务冲突策略校验。
- 生产者使用事务 Outbox；发布失败可以重试，但不得重做已经提交的业务事务。
- 事件至少一次投递，消费者必须幂等；不承诺 exactly-once。
- `payload` 只携带完成消费所需的事实，不携带令牌、Cookie、密码或大对象正文。
- 事件字段只允许新增可选字段；新增可能由 Provider 输出的枚举值必须发布新的事件 Schema/Topic 版本。Consumer 仍必须容忍未知可选字段，并把未知枚举值隔离为不可执行事实，不能猜测处理。

### 3.3 错误码

- 错误码使用大写 snake case，必须先登记再使用；同一语义不设别名。
- HTTP 状态表达协议结果，`code` 表达稳定业务原因；Consumer 只能按二者与 `retryable` 分支，不解析 `message`。
- 400 输入非法，401 未认证，403 越权，404 可安全暴露的不存在，409 状态/版本/幂等冲突，422 可解析但不可处理，429 限流，5xx 服务故障。
- 新增错误码是向后兼容变更，但必须给出所属 operation/event、HTTP 状态、可否重试和用户展示策略。
- 删除、改名或改变重试语义属于破坏性变更。

### 3.4 幂等键

外部副作用、资金、支付、退款、发布、外呼、分配、提现和人工调整必须携带幂等键。HTTP 使用 `Idempotency-Key` 请求头；Provider 回调使用已经验签的 Provider event ID；事件信封同时携带投递键 `eventId` 与业务键 `idempotencyKey`。每个 operation/event 的精确格式由 `registry.json` 冻结，例如：

```text
PUBLICATION_CHARGE:{channelPublicationId}
```

同一作用域内，同一键加同一标准化请求必须返回首次结果；同一键加不同请求摘要返回 409 `IDEMPOTENCY_CONFLICT`。同一事件 `eventId` 重放必须保持字节稳定；同一业务 `idempotencyKey` 加不同 payload 必须隔离并进入死信，不得执行。TTL、标准化算法、作用域和最终结果保留期必须在 `registry.json` 登记，不能由调用方自行猜测。幂等记录不得早于业务追责期被删除。

## 4. 契约变更流程

```text
提案/影响分析 -> 修改规范与样例 -> 生成 SDK/Mock -> Provider 测试
-> Consumer 测试 -> 兼容性比较 -> 双方评审 -> integration -> Staging -> 发布基线
```

1. 创建 `contract/<WBS-ID>-<short-name>` 分支，PR 目标为 `integration`。
2. PR 描述列出生产者、所有消费者、数据库影响、幂等/租户语义、开关、回滚和弃用计划。
3. 先修改契约事实源、样例与 Fixture，再运行生成器；不得直接修改 SDK 生成文件掩盖差异。
4. Provider Owner 与至少一个 Consumer Owner 共同评审。资金、权限、支付、自动发布、外呼和数据导出再增加 QA/安全或财务评审。
5. CI 全绿后才能合入每日 11:30 或 18:00 集成窗口；窗口外只处理已确认的阻塞缺陷。
6. Staging 验证通过后，将同一份规范复制到版本基线并打 `contracts-vX.Y.Z` 标签；基线不可改写。

紧急修复仍必须提交契约和测试。可以缩短评审等待，但不能关闭破坏性变更、租户隔离或资金幂等测试。

## 5. 版本与兼容规则

契约使用 SemVer：

任何 OpenAPI、AsyncAPI 或 registry 制品变化都必须推进契约版本，并同步 SDK 与 Mock 包版本；同版本制品漂移由 CI 阻断。版本提升不豁免兼容性检查。

- PATCH：描述、示例、非语义校正，或不改变生成类型的补充。
- MINOR：新增可选字段、路径、事件、错误码，或给请求输入增加 Provider 可接受的枚举值；旧 Consumer 无需修改即可继续运行。
- MAJOR：删除/改名、类型收窄、字段变必填、状态含义改变、Topic 地址变化、鉴权或幂等语义改变。

以下均由破坏性变更门禁阻止：

- 删除路径、方法、成功/错误响应、Topic、消息、Schema 或既有枚举值；
- 改变 `operationId`、事件类型、字段名、类型、格式、nullable 或必填性；
- 给既有请求增加必填参数/请求体；
- 将可接受输入范围收窄，或改变既有状态机的业务含义；
- 把可重试错误改为不可重试，或改变幂等作用域。
- 改变 HTTP Owner/Producer、删除既有 Consumer/Audience、改变安全方案，或改变事件消息编码。

若确需破坏性变更，不得用 CI 白名单跳过。应新增 `/v2`、`.v2` Topic 或新的契约主版本，并按“新旧双跑—消费者迁移—观测归零—弃用—移除”执行。

## 6. 测试责任

| 层级 | 责任方 | 最低覆盖 |
| --- | --- | --- |
| Schema/生成一致性 | 契约 Owner | OpenAPI/AsyncAPI 可解析，JSON Schema 可校验，生成物无漂移 |
| Mock | 契约 Owner | 每个 operation/event 至少一个成功样例；关键路径含认证、越权、冲突、重复和失败样例 |
| Provider | 服务 Owner | 真实路由/发布器对固定 Fixture 的状态、信封、Schema、租户隔离和幂等行为 |
| Consumer | 调用方 Owner | SDK 编译、请求构造、响应/事件解析、未知可选字段、重复事件和失败分支 |
| 跨系统 | QA＋双方 Owner | 至少 12 条真实 E2E、Outbox/Inbox 重放、刷新持久化、跨租户反例和回滚 |

测试文件命名建议：

- Provider：`tests/contracts/provider/<operation-or-event>.contract.test.*`
- Consumer：`tests/contracts/consumer/<provider>-<operation-or-event>.contract.test.*`
- Fixture：`packages/contracts/platform/fixtures/<transport>/<scenario>.json`

Provider/Consumer 测试都必须读取规范 Fixture，不得复制一份近似 JSON。真实第三方尚未提供沙箱时，可以测试内部 Adapter 契约，但报告必须标记为 `STUB_ONLY`，不能记为真实接入完成。

## 7. CI 门禁

`.github/workflows/contracts.yml` 是公共契约强制检查。预期根脚本及含义如下：

| 脚本 | 含义 |
| --- | --- |
| `pnpm contracts:generate:check` | 重新生成 OpenAPI、AsyncAPI、Schema、注册表并检查无漂移 |
| `pnpm sdk:generate:check` | 重新生成 TypeScript SDK 并检查工作树无差异 |
| `pnpm sdk:package:test` | 打包 SDK tarball，并由临时真实 Consumer 验证根/Schema 导入与 TypeScript 编译 |
| `pnpm contracts:test:provider` | 运行所有 Provider 契约测试 |
| `pnpm contracts:test:consumer` | 运行所有 Consumer 契约测试 |
| `pnpm contracts:breaking --base-ref <ref>` | 自测门禁后，与可信目标分支比较 OpenAPI、AsyncAPI、registry 中的 Schema、所有权、错误、鉴权和幂等语义，并校验冻结基线哈希与不可改写性 |
| `pnpm typecheck` / `pnpm build` | 验证所有工作区消费者可编译和可构建 |

CI 还会校验：契约改动是否同步更新 SDK、样例、Fixture、SDK/Mock 包版本和变更记录；生成目录是否被手改；生产配置是否引用 Mock；制品中是否出现秘密。`pnpm contracts:generate` 会在严格限定的生成目录内删除已失效 JSON 制品，但永不改写冻结基线。

首次引入契约家族时，CI 仅在可信目标分支同时不存在 OpenAPI、AsyncAPI 与 registry 时自动执行一次 bootstrap；只缺其中一份立即失败。契约存在后不再携带 `--allow-bootstrap`。PR 校验还会把目标分支已有的每个基线文件逐字节比较，禁止修改、删除或向既有版本目录追加文件；手工运行必须显式给出可信提交或发布标签。

## 8. 冻结和完成定义

一个接口或事件只有同时满足以下条件才标记为 `FROZEN`：

- OpenAPI/AsyncAPI 与独立 JSON Schema 完整，含鉴权、状态、错误、幂等和限流语义；
- 至少一个成功、一个校验失败、一个权限/状态失败，以及适用的重复请求/事件样例；
- SDK 已生成并由至少一个 Consumer 编译使用；
- Mock 可健康启动，Fixture 可重复加载且不含真实数据；
- Provider 与 Consumer 契约测试通过；
- 破坏性变更比较、typecheck 和 build 通过；
- Owner、版本、弃用日期和未决第三方限制已经登记。

“页面能显示”“Mock 返回 200”或“单方口头确认”都不构成接口冻结。

## 9. 审批与所有权

- 契约总 Owner：DEV-B；产品语义复核：DEV-A；自动化/发布：DEV-E；Marketplace：DEV-C；CRM：DEV-D；数据：DEV-F；质量门禁：QA。
- CODEOWNERS 只负责路由评审，不替代业务 DRI。仓库接入真实 GitHub 组织后，必须把 `.github/CODEOWNERS` 中的 bootstrap 团队名映射为实际、可请求评审的团队，并在分支保护中设为 Required Reviewers。
- 资金、支付、提现和对账契约必须有 DEV-B、DEV-C/DEV-E、QA 以及财务中至少三方确认。

## 10. 例外与审计

例外必须记录：WBS、原因、风险、Owner、到期日、开关、回滚和补测计划。例外不得允许跨租户访问、明文秘密、账本不平、重复扣款/发布或跳过真实外部验签。到期未关闭的例外自动阻塞生产发布。
