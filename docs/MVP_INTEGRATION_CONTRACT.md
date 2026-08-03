# 我淘淘最小 MVP 跨模块接口契约与集成规则

契约版本：`1.0.0`

适用范围：模块 01-08。当前仓库仍只实现模块 04；本文件和
`packages/contracts` 只建立集成边界，不代表模块 02、03、05、06、07
已经实现。

## 1. 契约来源和优先级

本契约基于 `output/pdf/00-08` 的研发要求、当前 `apps/api`、
`apps/web` 和模块 04 数据模型整理。发生冲突时按以下顺序处理：

1. 已合入 `integration` 的 `packages/contracts` 类型和接口清单。
2. 本文的业务语义、状态流转和接入规则。
3. 各模块研发要求 PDF。
4. 模块内部实现细节。

任何模块不得在本地复制一套近似类型。需要改变共享字段、状态、错误码或
接口路径时，必须先修改 `packages/contracts`、本文和契约测试，并在 PR 中
列出所有调用方影响。

## 2. 当前现状和关键假设

- 架构保持一个 React 前端、一个 Fastify 模块化单体、一个主数据库。
- `apps/api` 当前只有内容审核路由；`apps/web` 当前只有运营审核界面。
- 模块 04 的审核状态、版本门禁、追加式记录和权限检查已经可运行，本轮冻结，
  不增加自动审核、申诉、复杂风控或发布功能。
- 当前开发身份通过 `x-role`、`x-user-id`、`x-user-name`、
  `x-merchant-id` 注入。它只能用于本地开发；生产环境必须由可信网关或认证
  中间件写入，不能信任公网客户端自报角色。
- 现有抖音/小红书发布能力的真实请求、鉴权、回调签名、错误码和限流资料尚未
  在仓库中提供。模块 05 可以围绕内部标准适配器开发，但真实 HTTP 回调体在
  资料确认前保持 provider-specific，不能把本地 Mock 当作真实接入完成。
- 商品 `price` 暂按 JSON `number | null` 交换；币种和金额精度需要商品负责人
  在实现前确认。若确认结果不同，必须先变更契约。
- 内容 `style` 暂为非空字符串，不提前发明风格枚举；AI 内容负责人若要冻结
  枚举，需通过契约变更 PR。
- `ContentDetail` 在生成完成前允许 `title`、`copy`、`videoUrl` 为 null；只有
  素材完整且视频可播放时才能提交审核。

## 3. 模块输入、输出和依赖

| 模块 | 依赖 | 主要输入 | 必须输出 | 数据所有权 |
| --- | --- | --- | --- | --- |
| 01 公共契约 | 无 | PDF 00-08、现有实现 | 共享类型、状态、响应信封、接口清单、校验测试 | 公共枚举和契约文件 |
| 02 商品 | 01 | 当前商家上下文、商品表单和图片 | `productId`、商家归属、可供内容/公开页读取的商品资料 | `Product` 及商品图片元数据 |
| 03 AI 内容 | 01、02 | 当前商家、ACTIVE 商品、生成参数 | `contentId`、生成任务、可播放素材、`contentVersion`、提交审核状态 | `Content` 和生成任务；现有模块 04 的 Content 表由本模块接管演进 |
| 04 内容审核 | 01、03 | `PENDING_REVIEW` 内容及当前版本 | 追加式 `ReviewRecord`、`APPROVED` 或 `REJECTED`、发布门禁 | `Review`；只更新 Content 审核状态 |
| 05 自动发布 | 01、04、现有发布系统 | APPROVED 内容、渠道、脱敏账号、幂等键 | `publicationId`、发布状态、外部作品 ID/URL、失败信息 | `Publication`、执行尝试、回调事件摘要 |
| 06 买家浏览 | 01、02、05 | SUCCEEDED 发布记录和公开商品字段 | 公开 feed、商品页、来源上下文 | 公开查询模型；不拥有上游业务记录 |
| 07 询盘 | 01、02、05；由 06 发起 | 买家表单、`productId`、可选 `publicationId` | `inquiryId`、服务端补全的来源、状态历史 | `Inquiry` 和询盘状态历史 |
| 08 集成验收 | 02-07 | 固定测试数据、各模块 API、真实测试账号 | E2E 证据、测试报告、已知限制、上线检查 | 测试夹具和验收记录 |

代码可以并行开发，但联调顺序必须为：

`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08`

模块 06 和 07 可在模块 05 的内部契约 Stub 上并行，但最终验收必须切换为真实
SUCCEEDED 发布记录。

## 4. 公共约定

### 4.1 ID

所有业务 ID 由后端生成、全局唯一、不可复用，JSON 中始终为字符串。名称、
标题、URL 和外部作品 ID 不能替代内部关联 ID。

| 对象 | 字段 | 前缀 |
| --- | --- | --- |
| 商家 | `merchantId` | `mer_` |
| 商品 | `productId` | `prd_` |
| 内容 | `contentId` | `cnt_` |
| 授权账号引用 | `accountId` | `acc_` |
| 发布记录 | `publicationId` | `pub_` |
| 询盘 | `inquiryId` | `inq_` |
| 审核记录 | `reviewId` | `rev_` |
| 生成任务 | `generationRequestId` | `gen_` |

`requestId` 和第三方 `externalTaskId`、`externalWorkId` 是不透明字符串，不套用
业务 ID 前缀。前端不得解析、排序或计算任何 ID。

### 4.2 请求上下文和数据隔离

- `MERCHANT` 请求的 `merchantId` 必须来自可信身份上下文，创建/修改请求体
  不接受所属商家字段。
- 商家查询必须默认附加 `merchantId` 条件。对其他商家资源统一返回
  `FORBIDDEN` 或不泄露存在性的 `NOT_FOUND` 语义；同一模块内必须一致。
- `OPERATOR` 的审核、发布、重试和状态修正必须记录操作者和时间。
- PUBLIC 接口不读取调用方自报角色，也不返回内部审核、运营或授权凭证字段。

### 4.3 响应、错误和 HTTP 状态

所有成功响应：

```json
{
  "data": {},
  "requestId": "opaque-request-id"
}
```

所有失败响应：

```json
{
  "errorCode": "CONTENT_NOT_APPROVED",
  "message": "内容尚未审核通过",
  "requestId": "opaque-request-id",
  "details": {}
}
```

- `details` 可省略，只放字段错误、当前状态、当前版本等机器可用上下文。
- 400：参数或业务输入不合法；401：未认证；403：越权；404：允许暴露的资源
  不存在；409：版本、状态或幂等冲突；429：限流；500：未处理异常。
- `errorCode` 必须来自 `ERROR_CODES`。禁止用同义别名，例如同时出现
  `NOT_APPROVED` 和 `CONTENT_NOT_APPROVED`。
- `message` 面向人阅读，可以调整；调用方只能根据 HTTP 状态和 `errorCode`
  分支。

### 4.4 分页

- 查询参数统一为 `page`、`pageSize`，均为正整数。
- 默认 `page=1`、`pageSize=20`，`pageSize` 最大 100。
- 响应 `data` 统一为 `{ items, page, pageSize, total }`。
- 排序必须稳定；同一排序字段相等时增加业务 ID 作为最终排序键。

### 4.5 时间和审计

- 数据库存 UTC；接口输出 ISO 8601 UTC 且以 `Z` 结尾。
- 前端只负责按用户时区展示，不能把本地格式写回 API。
- 按公共要求，业务表至少保留 `createdAt`、`updatedAt`；事件还要保留明确的
  业务时间，例如 `reviewedAt`。
- 审核、发布发起、发布重试、回调处理和询盘状态修改必须保存操作者/来源、
  时间和前后状态。

### 4.6 幂等和重复事件

- `POST /publications` 的请求体必须包含 `idempotencyKey`。
- 同一 `idempotencyKey` 和同一标准化请求返回同一 `publicationId`；同一键但
  请求内容不同返回 409 `IDEMPOTENCY_CONFLICT`。
- `POST /publications/{publicationId}/retry` 使用新的 `idempotencyKey`，
  记录新的执行尝试，不覆盖历史尝试。
- 发布成功后普通重试不能把 `SUCCEEDED` 改回其他状态。
- 外部回调在验签/可信来源校验后，以 provider event ID 去重；没有事件 ID 时
  使用经过确认的稳定摘要策略。重复回调返回已接收，不重复触发后续动作。
- AI 生成和询盘防重复的具体时间窗由各模块负责人确认；不得复用发布幂等键
  语义冒充。

## 5. 状态机

### 5.1 商品

```text
DRAFT ──activate──> ACTIVE ──deactivate──> INACTIVE
  └──deactivate──────────────────────────> INACTIVE
INACTIVE ──activate──> ACTIVE
```

INACTIVE 商品不能创建新内容，但历史内容、发布和询盘不删除。

### 5.2 内容和生成任务

```text
DRAFT ──生成成功──> GENERATED ──提交审核──> PENDING_REVIEW
                                              ├──通过──> APPROVED
                                              └──驳回──> REJECTED
REJECTED ──修改并提高 contentVersion 后重新提交──> PENDING_REVIEW
```

生成任务单独使用 `QUEUED → PROCESSING → SUCCEEDED | FAILED`。生成失败不应
伪造内容状态成功；`PENDING_REVIEW` 不允许商家修改；`APPROVED` 只读并可进入
发布。

### 5.3 发布

```text
QUEUED ──执行器接收──> PUBLISHING ──可信结果──> SUCCEEDED
   └──明确失败──> FAILED <──明确失败──────────────┘
FAILED ──人工重试并新增尝试记录──> QUEUED
```

网络超时且外部状态未知时保持 `PUBLISHING`，先查询外部任务，不得直接新建第二
个作品。`SUCCEEDED` 为终态。

### 5.4 询盘

```text
NEW ──> CONTACTED ──> QUOTED ──> WON
 │           │           └──────> LOST
 └───────────┴──────────────────> LOST
```

`WON`、`LOST` 为 MVP 终态，不实现重新打开。

## 6. HTTP 接口契约

下表中的“输出”指成功信封的 `data`。完整角色、错误码和幂等元数据以
`MVP_API_CONTRACTS` 为可执行清单。

### 6.1 模块 01

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `GET /health` | 无 | `{ status: "ok" }` | PUBLIC |

### 6.2 模块 02

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `POST /products` | `CreateProductInput`；不含 `merchantId` | `Product` | MERCHANT |
| `GET /products` | `ProductListQuery` | `ProductPage` | MERCHANT |
| `GET /products/{productId}` | 路径 ID | `Product` | MERCHANT/OPERATOR |
| `PUT /products/{productId}` | `UpdateProductInput` | `Product` | MERCHANT |
| `POST /products/{productId}/activate` | 路径 ID | `Product` | MERCHANT |
| `POST /products/{productId}/deactivate` | 路径 ID | `Product` | MERCHANT |
| `POST /uploads/product-images` | `multipart/form-data` | `ProductImageUploadResult` | MERCHANT |

创建 AI 内容的最低商品资料是名称和至少一个卖点，且商品必须为 ACTIVE。

### 6.3 模块 03

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `POST /contents/generate` | `GenerateContentInput` | `ContentGenerationStatusResult` | MERCHANT |
| `GET /contents/{contentId}` | 路径 ID | `ContentDetail` | MERCHANT/OPERATOR |
| `GET /contents/{contentId}/generation-status` | 路径 ID | `ContentGenerationStatusResult` | MERCHANT |
| `PUT /contents/{contentId}` | `UpdateContentInput`，含当前 `contentVersion` | `ContentDetail` | MERCHANT |
| `POST /contents/{contentId}/regenerate` | `RegenerateContentInput` | `ContentGenerationStatusResult` | MERCHANT |
| `POST /contents/{contentId}/submit-review` | `SubmitReviewInput` | `ContentDetail` | MERCHANT |

生成接口必须快速返回任务标识，不能让单个 HTTP 请求无限等待。提交审核前必须
验证视频可播放、必填内容完整，并原子地写入 `submittedAt` 和
`PENDING_REVIEW`。

### 6.4 模块 04

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `GET /reviews/pending` | `PendingReviewsQuery` | `PendingReviewsPage` | OPERATOR |
| `GET /reviews/{contentId}` | 路径 ID | `ReviewContentDetail` | OPERATOR |
| `POST /reviews/{contentId}/approve` | `ApproveReviewInput` | `ReviewDecisionResult` | OPERATOR |
| `POST /reviews/{contentId}/reject` | `RejectReviewInput` | `ReviewDecisionResult` | OPERATOR |
| `GET /contents/{contentId}/review-history` | 路径 ID | `ReviewRecord[]` | MERCHANT/OPERATOR |

审核写入条件必须同时匹配 `contentId + contentVersion + PENDING_REVIEW`。驳回
`comment` 必填且对所属商家可见；通过备注对商家隐藏。

### 6.5 模块 05

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `GET /authorized-accounts` | `AuthorizedAccountsQuery` | `AuthorizedAccount[]` | OPERATOR |
| `POST /publications` | `CreatePublicationInput`，含幂等键 | `Publication` | OPERATOR |
| `GET /publications/{publicationId}` | 路径 ID | `Publication` | MERCHANT/OPERATOR |
| `GET /publications` | `PublicationListQuery` | `PublicationPage` | MERCHANT/OPERATOR |
| `POST /publications/{publicationId}/retry` | `RetryPublicationInput` | `Publication` | OPERATOR |
| `POST /publications/callback` | provider-specific，经校验后标准化 | `PublicationCallbackAck` | 可信外部系统 |

`NormalizedPublicationCallback` 是发布适配层内部边界，不等于尚未确认的第三方
原始回调格式。任何商家响应都不能包含令牌、密码、Cookie、签名密钥或内部
鉴权字段。

### 6.6 模块 06

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `GET /feed` | `FeedQuery` | `FeedPage` | PUBLIC |
| `GET /storefront/products/{productId}` | 可选 `publicationId` | `StorefrontProduct` | PUBLIC |
| `GET /storefront/merchants/{merchantId}` | 路径 ID | `StorefrontMerchant` | PUBLIC |
| `GET /storefront/publications/{publicationId}` | 路径 ID | `StorefrontPublication` | PUBLIC |

feed 只能读取 `SUCCEEDED` 发布。停用商品不进入新列表；历史外链返回友好
不可用状态。`publicationId` 必须保留到询盘表单。公开 DTO 不返回
`accountId`；询盘服务根据 `publicationId` 在服务端补全账号来源。

### 6.7 模块 07

| 方法和路径 | 输入 | 输出 | 权限 |
| --- | --- | --- | --- |
| `POST /inquiries` | `CreateInquiryInput` | `InquiryCreated` | PUBLIC |
| `GET /merchant/inquiries` | `MerchantInquiriesQuery` | `InquiryPage` | MERCHANT |
| `GET /merchant/inquiries/{inquiryId}` | 路径 ID | `InquiryDetail` | MERCHANT |
| `PATCH /inquiries/{inquiryId}/status` | `UpdateInquiryStatusInput` | `InquiryDetail` | MERCHANT/OPERATOR |

公开创建请求只接受买家输入、`productId`、可选 `publicationId` 和 referrer。
`merchantId`、`contentId`、`channel`、`accountId`、`externalWorkId` 必须由服务端
根据商品/发布记录补全并校验，不能信任前端提交。

## 7. Mock / Stub 边界

| 模块 | 允许的 Mock / Stub | 禁止伪装为完成 |
| --- | --- | --- |
| 01 | 固定 ID、信封、状态和错误夹具 | 另一套只供页面展示的字段 |
| 02 | 下游可临时 Stub “按 productId 读取公开/生成所需字段” | 绕过 merchantId 隔离或把商品名称当关联键 |
| 03 | 可 Stub AI 生成器，覆盖处理中、成功、失败 | Stub 直接把内容改成 APPROVED，或替审核模块决定 |
| 04 | 使用固定上游 Content 种子；审核本身使用现有真实实现 | 扩展自动风控、申诉或发布 |
| 05 | 取得真实接口资料后，可按内部 Publisher 适配器 Stub 成功、处理中、失败、重复事件 | 未取得资料时宣称真实发布已接入；在 Mock 中存放真实凭证 |
| 06 | 可 Stub 成功发布查询和公开商品读取 | 展示 QUEUED/PUBLISHING/FAILED 内容 |
| 07 | 可 Stub publication 查询以测试服务端归因补全 | 直接保存客户端提交的 merchant/channel/account 来源 |
| 08 | 可在开发回归中组合模块 Stub | 最终 E2E、真实发布和真实询盘使用 Stub |

Stub 与正式实现必须共享 `packages/contracts` 类型。替换 Stub 时不得修改前端
字段名来迁就实现。

## 8. 各模块集成验收清单

### 8.1 模块 01

- [ ] `MVP_API_CONTRACTS` 路径、角色、输入、输出、错误和幂等规则自检通过。
- [ ] 状态枚举和允许流转没有同义重复。
- [ ] 成功、错误、分页和 UTC 时间校验器可供各模块测试复用。
- [ ] 契约变更同时更新本文、类型、测试和受影响模块说明。

### 8.2 模块 02

- [ ] 商家创建商品后返回 `prd_` ID，归属从服务端上下文取得。
- [ ] 列表和详情按 merchantId 隔离；商家 B 无法读取商家 A。
- [ ] 名称、至少一个卖点和价格模式执行服务端校验。
- [ ] ACTIVE 商品可被模块 03 读取；INACTIVE 被拒绝生成。
- [ ] 停用不物理删除历史关联，公开 DTO 不含内部字段。
- [ ] 迁移可从空库执行，成功/参数错误/越权有测试。

### 8.3 模块 03

- [ ] 接管并兼容现有 Content 表，迁移不破坏模块 04 种子和测试。
- [ ] 只读取当前商家的 ACTIVE 商品且校验最低资料。
- [ ] 生成接口返回 `cnt_` 和 `gen_` 标识，状态可轮询。
- [ ] 失败保留输入且可重试；重复点击不创建明显重复任务。
- [ ] 修改使用 `contentVersion` 做并发控制并提高版本。
- [ ] 提交审核原子进入 PENDING_REVIEW；审核中不能修改。
- [ ] 其他商家无法读取或修改内容。

### 8.4 模块 04

- [x] 待审核分页结构、过滤和稳定排序符合公共契约。
- [x] 通过/驳回校验当前版本和 PENDING_REVIEW 状态。
- [x] 同一版本只产生一条追加式审核记录，并处理并发冲突。
- [x] 驳回原因对所属商家可见，通过内部备注隐藏。
- [x] 非运营角色无法调用审核操作。
- [x] 发布门禁对非 APPROVED 内容返回 `CONTENT_NOT_APPROVED`。

本轮审计未发现会阻塞契约接入的模块 04 P0 业务问题。现有开发请求头信任模型
不是生产鉴权方案，但仓库 README 已明确其本地开发边界。当前追加式 Review
表只有 `reviewedAt`、没有公共要求中的 `createdAt/updatedAt`；这是非阻塞的
P1 数据规范差异，本轮按“只修 P0”原则不增加迁移，后续首次修改 Review 表时
补齐。

### 8.5 模块 05

- [ ] 真实接口文档、鉴权、账号查询、回调、错误码、限流和测试环境已确认。
- [ ] 账号响应只含 `accountId` 和脱敏展示字段。
- [ ] 后端再次调用审核门禁，未批准内容不触发外部系统。
- [ ] 创建和重试执行幂等规则；重复键不产生第二个作品。
- [ ] 网络超时先查外部状态，未知时保持 PUBLISHING。
- [ ] 回调验签/可信来源、事件去重和原始摘要保存均有测试。
- [ ] 失败和重试保留独立执行记录及操作者。
- [ ] 至少一个真实测试账号返回作品 ID 和 URL。
- [ ] 所有响应和日志均不泄露授权凭证。

### 8.6 模块 06

- [ ] feed 只展示 SUCCEEDED 发布且分页稳定。
- [ ] 内容、商品、商家和 publication 关联正确。
- [ ] 外部链接进入后持续传递 publicationId 和渠道来源。
- [ ] 商品停用、无效链接和视频失败有友好状态。
- [ ] PUBLIC DTO 不含审核、运营或授权账号秘密字段。
- [ ] 移动端可浏览、进入详情并发起询盘。

### 8.7 模块 07

- [ ] 公开表单校验姓名、联系方式和需求，并有最小限流。
- [ ] 来源由服务端根据 publicationId 校验和补全。
- [ ] 商家列表、详情和修改全部按 merchantId 隔离。
- [ ] 状态只按允许路径流转，WON/LOST 不可重开。
- [ ] 每次状态修改记录前后状态、操作者、时间和备注。
- [ ] 重复提交和来源篡改返回稳定错误。
- [ ] 日志不输出完整联系方式，响应按角色控制敏感字段。

### 8.8 模块 08

- [ ] IT-01 至 IT-10 有可重复执行的请求和证据。
- [ ] 空库迁移、typecheck、test、build 全部通过。
- [ ] 商家 A 成功路径和商家 B 越权路径均通过。
- [ ] 未审核发布、超时查询、重复幂等键、重复回调和失败重试均通过。
- [ ] 至少一个渠道完成真实发布并保存作品 ID/URL。
- [ ] 真实商品页提交询盘，来源链路完整且不可篡改。
- [ ] 生产配置无测试密钥、Mock 地址或敏感日志。
- [ ] 演示脚本、已知限制、回滚方式和上线检查表已提交。

## 9. PR 接入规则

1. 所有模块 PR 的目标分支为 `integration`，不得直接修改或合并到 `main`。
2. 一个 PR 只处理一个模块或一次明确的公共契约变更，不顺手重构无关文件。
3. 开发前同步最新 `origin/integration`；出现契约冲突时先解决契约，不在模块内
   加兼容别名。
4. 共享数据库表所有权按第 3 节执行。跨所有权修改必须在 PR 说明迁移影响和
   对方模块验证结果。
5. API PR 至少包含一个成功、一个参数错误、一个权限/状态错误测试；分页接口
   使用 `isPage`，信封使用 `isSuccessResponse` / `isErrorResponse`。
6. 数据库变更必须带可重复执行的迁移；从空库执行并保留历史数据语义。
7. Mock 必须通过明确的适配器或仓储边界注入，默认配置和生产配置不能指向 Mock。
8. 契约变更 PR 必须列出调用方、数据库、前端和测试影响，并更新：
   `packages/contracts`、本文件、契约测试和变更摘要。
9. 合并前必须执行：

```bash
pnpm install --frozen-lockfile
pnpm --filter @wotao/review-api db:generate
pnpm typecheck
pnpm test
pnpm build
```

10. PR 描述必须写明：完成范围、未完成范围、可联调接口、测试方式、迁移、契约
    变更、已知限制和需要其他模块确认的事项。

## 10. 最小契约校验框架

- `MVP_MODULES`：运行时可读的依赖和交付清单。
- `MVP_API_CONTRACTS`：运行时可读的 method/path/角色/类型/错误/幂等清单。
- `MvpApiOperationMap`：编译期输入输出映射；消费者可使用
  `MvpApiRequest<operationId>` 和 `MvpApiResponse<operationId>`。
- `validateMvpApiContracts()`：检查重复 operation、重复路由、角色和发布幂等。
- `isSuccessResponse`、`isErrorResponse`、`isPage`、`isIsoUtcDateTime`：
  模块接口测试的最小运行时断言。
- `packages/contracts/tests/contract-manifest.test.ts`：冻结上述约定。
- `scripts/generate-openapi.ts`：从 `MVP_API_CONTRACTS` 和共享枚举生成 OpenAPI；
  `pnpm openapi:check` 阻止生成物漂移。
- `apps/mock-api`：从生成后的 OpenAPI 读取路由、角色、ID 前缀和状态流转，不再
  维护模块私有的公共常量。
- `packages/contracts/tests/openapi-consistency.test.ts`：校验 TypeScript manifest、
  OpenAPI 元数据、响应信封、枚举、状态流转和 ID 前缀一致。
- `apps/api/tests/review-api.test.ts`：模块 04 已接入公共信封和分页断言，作为后续
  模块测试样例。

本框架只验证共享契约和接口兼容性，不替代各模块的业务测试或模块 08 的真实
端到端测试。

## 11. 仍需负责人确认

| 事项 | 负责人 | 阻塞范围 |
| --- | --- | --- |
| 抖音/小红书接口、鉴权、账号字段、回调签名、事件 ID、限流和测试环境 | 模块 05 / 项目方 | 真实发布和最终 E2E |
| 商品金额序列化、币种和精度 | 模块 02 / 产品 | FIXED 价格展示 |
| AI 服务接口、生成任务状态映射、是否冻结 style 枚举 | 模块 03 | 真实生成 |
| 授权账号可展示字段和“可用”判定 | 模块 05 | 账号选择 UI |
| 询盘联系方式规则、重复识别时间窗和限流阈值 | 模块 07 / 产品 | 公开提交 |
| 生产身份网关、请求 ID 透传和运营权限来源 | 模块 01 / 基础开发 | 生产安全 |
