# 全平台 Topic 与事件契约注册表

版本：V1.0（Contract Freeze 候选）  
事实源：`packages/contracts/src/platform/event-contracts.ts`

本文是人工联调索引；生成器、Broker ACL、AsyncAPI、Fixture 与契约测试必须直接读取
`PLATFORM_EVENT_CONTRACTS`，不得从 Markdown 反向解析，也不得在服务仓库维护第二份事件字段。
当前注册源覆盖 69 个跨系统事件/异步命令，包含身份、企业、商城、库存、订单、退款、
CRM、内容发布、OPC、会员、积分、现金账本与数据消费链路。

## 1. Topic 地址与所有权

注册表的 `topic` 是不含环境的唯一 logical Topic。Broker 上的物理地址固定为：

```text
wotao.{environment}.{logicalTopic}
```

例如 DEV 的 `commerce.order.paid.v1` 对应
`wotao.dev.commerce.order.paid.v1`。`environment` 只允许
`DEV/TEST/STAGING/PROD`，消息信封中的环境必须与 Broker namespace 一致。

每个 logical Topic 只拥有一个 `eventType`、一个 `schemaVersion` 和一个登记生产者。
Broker principal 与 Topic ACL 才能证明生产者身份；信封里的 `producer` 只用于一致性校验。
消费者在反序列化前校验 principal、Topic、eventType、schemaVersion、environment 和 audience，
再校验企业及业务对象归属。错主体、错 Topic、错租户、错 audience 或未知 schema 进入安全隔离，
不得推进业务游标或产生发布、分配、入账、冲正、提现副作用。

## 2. 统一事件信封

所有注册消息使用同一 Draft 2020-12 信封；示例时间统一为 UTC `Z`：

```json
{
  "eventId": "evt_order_paid_001",
  "eventType": "OrderPaid",
  "schemaVersion": 1,
  "occurredAt": "2026-08-10T02:00:00Z",
  "publishedAt": "2026-08-10T02:00:01Z",
  "producer": "SYS-02",
  "environment": "DEV",
  "audience": ["SYS-03", "SYS-04", "SYS-06", "SYS-08"],
  "enterpriseId": "ent_contract_001",
  "aggregateType": "Order",
  "aggregateId": "ord_contract_001",
  "aggregateVersion": 2,
  "traceId": "trace_contract_fixture_001",
  "causationId": null,
  "correlationId": "corr_contract_fixture_001",
  "idempotencyKey": "PAYMENT_SUCCESS:pay_contract_001:txn_contract_001",
  "payload": {}
}
```

规则如下：

- `eventId` 在 Outbox 首次创建，重试和重放不改变；禁止另建 `eventVersion`。
- `occurredAt` 是业务事实时间，`publishedAt` 是 Outbox 发出时间，二者都输出 UTC `Z`。
- `enterpriseId` 在消费者公共或平台级事实中可为 `null`；领域 payload 中的主体字段仍须按 schema 校验。
- `aggregateVersion` 防止旧事件覆盖新投影，不能用消息到达顺序代替版本判断。
- `idempotencyKey` 是业务防重；消费者还需用 `eventId + consumerName` 建 Inbox 唯一键。
- 信封及 payload 禁止密码、Cookie、Token、完整收款资料、完整联系方式、原始回调和媒体正文。

`PLATFORM_EVENT_SCHEMAS` 按 eventType 导出完整信封 JSON Schema；每个 descriptor 的
`payloadSchema` 是独立 payload Schema，`example` 是完整可执行信封 Fixture。

## 3. 身份、企业与控制面

| logical Topic | eventType | 生产者 | consumers/audience | 幂等键模板 |
|---|---|---|---|---|
| `platform.identity.user.registered.v1` | `UserRegistered` | SYS-01 | SYS-01 | `USER_REGISTERED:{userId}:{userVersion}` |
| `platform.enterprise.initialized.v1` | `EnterpriseInitialized` | SYS-01 | SYS-03/04/05/06/08 | `INIT_ENTERPRISE_BENEFITS:{enterpriseId}` |
| `platform.enterprise.profile_updated.v1` | `EnterpriseProfileUpdated` | SYS-01 | SYS-03/04/05/06 | `ENTERPRISE_PROFILE:{enterpriseId}:{profileVersion}` |
| `platform.enterprise.review-changed.v1` | `EnterpriseReviewChanged` | SYS-01 | SYS-03/04/05 | `ENTERPRISE_REVIEW:{reviewSubmissionId}:{decisionVersion}` |
| `platform.enterprise.whitelist-changed.v1` | `EnterpriseWhitelistChanged` | SYS-01 | SYS-03/04/05/06/08 | `ENTERPRISE_WHITELIST:{scopeRef}:{version}` |
| `platform.enterprise.member_changed.v1` | `EnterpriseMemberChanged` | SYS-01 | SYS-03/04/05/06/08 | `ENTERPRISE_MEMBER:{enterpriseMemberId}:{version}` |
| `platform.feature-flag.changed.v1` | `FeatureFlagChanged` | SYS-01 | SYS-02/03/04/05/06/07/08 | `FEATURE_FLAG:{flagCode}:{scopeType}:{scopeId}:{version}` |
| `platform.agent.tool-execution-reported.v1` | `AgentToolExecutionReported` | 登记领域适配器 | SYS-01 | `AGENT_TOOL_RESULT:{agentRunId}:{toolRunId}:{resultVersion}` |
| `platform.agent.run-status-changed.v1` | `AgentRunStatusChanged` | SYS-01 | SYS-04/05/06 | `AGENT_RUN_STATUS:{agentRunId}:{agentRunVersion}` |
| `commerce.consumer.trial-access-changed.v1` | `ConsumerTrialAccessChanged` | SYS-02 | SYS-01/06 | `CONSUMER_TRIAL_ACCESS:{trialAccessId}:{version}` |

领域别名 `MarketingAgentExecutionReported` 和 `ContentPublishingAgentExecutionReported` 不登记为
并列事实 Topic。登记适配器必须用相同 `toolRunId/resultVersion/payloadHash` 归一化为
`AgentToolExecutionReported`；SYS-06 只消费 `AgentRunStatusChanged` 统计智能体运行终态。

## 4. 商品、库存、订单、售后与评价

| logical Topic | eventType | 生产者 | consumers/audience | 幂等键模板 |
|---|---|---|---|---|
| `commerce.product.published.v1` | `ProductPublished` | SYS-03 | SYS-02/04/05/06 | `PRODUCT_PUBLISHED:{productId}:{productVersion}` |
| `commerce.inventory.changed.v1` | `InventoryChanged` | SYS-03 | SYS-02/06 | `INVENTORY_CHANGED:{skuId}:{inventoryVersion}` |
| `commerce.inventory-reservation.created.v1` | `InventoryReservationCreated` | SYS-03 | SYS-02 | `INVENTORY_RESERVE:{orderId}` |
| `commerce.inventory-reservation.committed.v1` | `InventoryReservationCommitted` | SYS-03 | SYS-02 | `INVENTORY_COMMIT:{reservationId}:{paymentId}` |
| `commerce.inventory-reservation.released.v1` | `InventoryReservationReleased` | SYS-03 | SYS-02 | `INVENTORY_RELEASE:{reservationId}:{reason}` |
| `commerce.content.product-clicked.v1` | `ContentProductClicked` | SYS-02 | SYS-04/06 | `CONTENT_PRODUCT_CLICK:{attributionCandidateId}` |
| `commerce.order.attribution-frozen.v1` | `OrderAttributionFrozen` | SYS-02 | SYS-04/06/08 | `ORDER_ATTRIBUTION:{attributionId}:{version}` |
| `commerce.order.attribution-adjusted.v1` | `OrderAttributionAdjusted` | SYS-02 | SYS-04/06/08 | `ORDER_ATTRIBUTION_ADJUST:{adjustmentId}:{newVersion}` |
| `commerce.order.paid.v1` | `OrderPaid` | SYS-02 | SYS-03/04/06/08 | `PAYMENT_SUCCESS:{paymentId}:{channelTransactionId}` |
| `commerce.order.cancelled.v1` | `OrderCancelled` | SYS-02 | SYS-03/06 | `ORDER_CANCEL:{orderId}` |
| `commerce.order.shipment-registered.v1` | `OrderShipmentRegistered` | SYS-02 | SYS-03/06 | `SHIPMENT_REGISTER:{fulfillmentId}:{fulfillmentVersion}` |
| `commerce.order.received.v1` | `OrderReceived` | SYS-02 | SYS-03/06/08 | `ORDER_RECEIVED:{orderId}` |
| `commerce.order.settlement-eligible.v1` | `OrderSettlementEligible` | SYS-02 | SYS-03/06/08 | `ORDER_SETTLEMENT_ELIGIBLE:{subOrderId}:{eligibilityVersion}` |
| `commerce.aftersale.status-changed.v1` | `AftersaleStatusChanged` | SYS-02 | SYS-03/06/08 | `AFTERSALE_STATUS:{aftersaleId}:{version}` |
| `commerce.refund.requested.v1` | `RefundRequested` | SYS-02 | SYS-03/06/08 | `REFUND_REQUEST:{refundId}:{requestVersion}` |
| `commerce.refund.status-changed.v1` | `RefundStatusChanged` | SYS-02 | SYS-03/06/08 | `REFUND_STATUS:{refundId}:{version}` |
| `commerce.order.refunded.v1` | `OrderRefunded` | SYS-02 | SYS-03/04/06/08 | `REFUND_RESULT:{refundId}:{channelRefundTransactionId}` |
| `commerce.review.reply-changed.v1` | `ReviewReplyChanged` | SYS-02 | SYS-03/06 | `REVIEW_REPLY:{reviewId}:{replyVersion}` |
| `commerce.review.governance-changed.v1` | `ReviewGovernanceChanged` | SYS-02 | SYS-03/06 | `REVIEW_GOVERNANCE:{reviewId}:{governanceVersion}` |

`InventoryReservationCommitted` 与 `InventoryReservationReleased` 对同一预占互斥。
`RefundRequested/RefundStatusChanged` 不能代替 `OrderRefunded`；只有真实退款完成事实才触发账本冲正。
订单公开事件不含买家 PII，SYS-03/04/06 按登记 audience 使用不可变 ref/version/hash 回读裁剪快照。

## 5. CRM、外呼与微信接管

| logical Topic | eventType | 生产者 | consumers/audience | 幂等键模板 |
|---|---|---|---|---|
| `crm.lead.created.v1` | `LeadCreated` | SYS-04 | SYS-01/06 | `CRM_LEAD:{leadId}:{leadVersion}` |
| `crm.lead.status_changed.v1` | `LeadStatusChanged` | SYS-04 | SYS-01/06 | `CRM_LEAD_STATUS:{leadId}:{leadVersion}` |
| `crm.customer.updated.v1` | `CustomerUpdated` | SYS-04 | SYS-01/06 | `CRM_CUSTOMER:{customerId}:{customerVersion}` |
| `crm.customer.assigned.v1` | `CustomerAssigned` | SYS-04 | SYS-01/06 | `CRM_CUSTOMER_ASSIGN:{customerId}:{assignmentVersion}` |
| `crm.opportunity.stage-changed.v1` | `OpportunityStageChanged` | SYS-04 | SYS-01/06 | `CRM_OPPORTUNITY_STAGE:{opportunityId}:{opportunityVersion}` |
| `crm.call.completed.v1` | `CallCompleted` | SYS-04 | SYS-06 | `AI_CALL_RESULT:{providerAccountId}:{callId}:{resultVersion}` |
| `crm.wechat.handoff-requested.v1` | `WeChatHandoffRequested` | SYS-04 | SYS-06 | `WECHAT_HANDOFF:{handoffRef}:{handoffVersion}` |
| `crm.marketing.global-refusal-changed.v1` | `GlobalMarketingRefusalChanged` | SYS-04 | SYS-01/06 | `CRM_GLOBAL_REFUSAL:{customerId}:{refusalVersion}` |
| `crm.marketing.contact-suppression-changed.v1` | `ContactSuppressionChanged` | SYS-04 | SYS-01/06 | `CRM_CONTACT_SUPPRESSION:{suppressionId}:{suppressionVersion}` |

五类分析事实使用不可变 `analyticsSnapshotRef/version/hash` 补偿。事件和补偿游标都不传姓名、
联系方式、录音、摘要、微信标识或会话正文；同 ref 变 hash 或跨企业读取必须隔离且不推进游标。

## 6. 内容发布、费用与 OPC 账号

| logical Topic | eventType | kind | 生产者 | consumers/audience | 幂等键模板 |
|---|---|---:|---|---|---|
| `content.version.submitted.v1` | `ContentVersionSubmitted` | EVENT | SYS-05 | SYS-01/06 | `CONTENT_SUBMIT:{channelVersionId}:{contentVersion}` |
| `content.review.completed.v1` | `ContentReviewCompleted` | EVENT | 审核中心 | SYS-05/06 | `CONTENT_REVIEW:{reviewId}:{decisionVersion}` |
| `publication.confirmed.v1` | `PublicationConfirmed` | EVENT | SYS-05 | SYS-01/06/08 | `PUBLICATION_CONFIRM:{confirmationId}` |
| `ledger.publication-service-order.changed.v1` | `PublicationServiceOrderChanged` | EVENT | SYS-08 | SYS-01/05 | `PUBLICATION_SERVICE_ORDER:{channelPublicationId}:{sourceVersion}` |
| `ledger.publication.charge-reserved.v1` | `ChannelPublicationReserved` | EVENT | SYS-08 | SYS-05/06 | `PUBLICATION_CHARGE:{channelPublicationId}` |
| `publication.channel.first_visible.v1` | `ChannelPublicationFirstVisible` | EVENT | SYS-05 | SYS-06/07/08 | `PUBLICATION_FIRST_VISIBLE:{channelPublicationId}` |
| `publication.channel.effective.v1` | `ChannelPublicationEffective` | EVENT | SYS-05 | SYS-06/07/08 | `PUBLICATION_EFFECTIVE:{validPublicationId}` |
| `publication.channel.failed.v1` | `ChannelPublicationFailed` | EVENT | SYS-05 | SYS-06/07/08 | `PUBLICATION_FAILED:{channelPublicationId}:{sourceVersion}` |
| `publication.channel.refund-eligible.v1` | `ChannelPublicationRefundEligible` | EVENT | SYS-05 | SYS-06/08 | `LIABILITY_REFUND_ELIGIBLE:{validPublicationId}:{refundReasonCode}:{responsibilityVersion}` |
| `ledger.publication.charge-released.v1` | `ChannelPublicationChargeReleased` | EVENT | SYS-08 | SYS-05/06 | `PUB_CHARGE_REFUND:{validPublicationId}:{refundReasonCode}:{responsibilityVersion}` |
| `publication.account-assignment.requested.v1` | `AccountAssignmentRequested` | COMMAND | SYS-05 | SYS-07 | `ACCOUNT_ASSIGNMENT_REQUEST:{channelPublicationId}:{assignmentRequestVersion}` |
| `opc.account-assignment.completed.v1` | `AccountAssignmentCompleted` | EVENT | SYS-07 | SYS-05 | `ACCOUNT_ASSIGNMENT_RESULT:{channelPublicationId}:{assignmentRequestVersion}` |
| `opc.account-assignment.unavailable.v1` | `AccountAssignmentUnavailable` | EVENT | SYS-07 | SYS-05 | `ACCOUNT_ASSIGNMENT_RESULT:{channelPublicationId}:{assignmentRequestVersion}` |
| `publication.account-assignment.release-requested.v1` | `AccountAssignmentReleaseRequested` | COMMAND | SYS-05 | SYS-07 | `ACCOUNT_ASSIGNMENT_RELEASE:{accountAssignmentId}` |
| `opc.account-assignment.released.v1` | `AccountAssignmentReleased` | EVENT | SYS-07 | SYS-05 | `ACCOUNT_ASSIGNMENT_RELEASE:{accountAssignmentId}` |
| `opc.account.status-changed.v1` | `OpcAccountStatusChanged` | EVENT | SYS-07 | SYS-05/06 | `OPC_ACCOUNT_STATUS:{opcAccountId}:{accountVersion}` |
| `ledger.command.request-opc-earning-settlement.v1` | `RequestOpcEarningSettlement` | COMMAND | SYS-07 | SYS-08 | `OPC_EARNING:{validPublicationId}` |
| `ledger.opc-earning.settled.v1` | `OpcEarningSettled` | EVENT | SYS-08 | SYS-07 | `OPC_EARNING:{validPublicationId}` |
| `ledger.opc-earning.reversed.v1` | `OpcEarningReversed` | EVENT | SYS-08 | SYS-07 | `OPC_EARNING_REVERSE:{originalLedgerEntryId}` |

发布预占唯一冻结键是 `PUBLICATION_CHARGE:{channelPublicationId}`；旧文档中的
`PUB_CHARGE_RESERVE:*` 不得进入 API、事件、Fixture 或 Inbox/Outbox 表。
`ChannelPublicationReserved` 是 SYS-05 执行抖音发布的唯一资金/额度授权；支付回跳和
`PublicationServiceOrderChanged(PAID)` 都不能代替它。责任资格不等于返还完成，页面只在收到匹配的
`ChannelPublicationChargeReleased(status=COMPLETED)` 后展示已返还。

`AccountAssignmentCompleted` 固定携带 `accountAssignmentId/providerId/opcAccountId/channelAccountId`
以及 `assignmentSnapshotVersion`，但绝不携带会话秘密。会话授权不是事件，只能调用同步 API；
服务端必须同时匹配：

```text
accountAssignmentId + channelPublicationId + executionId + assignmentSnapshotVersion
```

## 7. 会员、积分、资金与数据事实

| logical Topic | eventType | 生产者 | consumers/audience | 幂等键模板 |
|---|---|---|---|---|
| `ledger.membership.changed.v1` | `MembershipChanged` | SYS-08 | SYS-01/05/06 | `MEMBERSHIP:{membershipId}:{membershipVersion}` |
| `ledger.benefit-quota.changed.v1` | `BenefitQuotaChanged` | SYS-08 | SYS-01/05/06 | `BENEFIT_QUOTA:{quotaAccountId}:{quotaVersion}` |
| `ledger.profit-base.frozen.v1` | `ProfitBaseFrozen` | SYS-08 | SYS-06 | `PROFIT_FREEZE:{subOrderId}:{settlementVersion}` |
| `ledger.profit-base.allocated.v1` | `ProfitBaseAllocated` | SYS-08 | SYS-06 | `PROFIT_ALLOCATE:{profitBaseId}:{targetPlanVersionId}` |
| `ledger.profit-base.reversed.v1` | `ProfitBaseReversed` | SYS-08 | SYS-06 | `PROFIT_REVERSE:{profitBaseId}:{originalAllocationVersion}` |
| `ledger.merchant-settlement.changed.v1` | `MerchantSettlementChanged` | SYS-08 | SYS-03/06 | `ORDER_SETTLE:{subOrderId}:{settlementVersion}` |
| `ledger.points-entry.posted.v1` | `PointsLedgerEntryPosted` | SYS-08 | SYS-01/06 | `POINTS_ENTRY:{pointsEntryId}` |
| `ledger.points-balance.changed.v1` | `PointsBalanceChanged` | SYS-08 | SYS-01 | `POINTS_BALANCE:{pointsAccountId}:{balanceVersion}` |
| `ledger.withdrawal.status-changed.v1` | `WithdrawalStatusChanged` | SYS-08 | SYS-01/06/07 | `WITHDRAWAL_STATUS:{withdrawalId}:{version}` |
| `ledger.cash-entry.posted.v1` | `CashLedgerEntryPosted` | SYS-08 | SYS-06 | `CASH_LEDGER_ENTRY:{ledgerEntryId}` |
| `ledger.enterprise-balance.changed.v1` | `EnterpriseBalanceChanged` | SYS-08 | SYS-01 | `ENTERPRISE_BALANCE:{enterpriseId}:{balanceVersion}` |
| `ledger.anomaly.detected.v1` | `LedgerAnomalyDetected` | SYS-08 | SYS-01/06 | `LEDGER_ANOMALY:{anomalyId}:{anomalyVersion}` |

`WithdrawalStatusChanged` 统一使用 `ownerType/ownerId`；企业为
`ENTERPRISE/{enterpriseId}`，OPC 为 `OPC_PROVIDER/{providerId}`。禁止再使用并列的顶层
`providerId` 或用企业主体冒充 OPC。

SYS-06 的平台净收益、企业收益和 OPC 成本只消费 `CashLedgerEntryPosted`。
`OpcEarningSettled`、`MerchantSettlementChanged`、`ProfitBase*`、余额摘要与订单金额都不能再次累计为现金。
积分只消费 `PointsLedgerEntryPosted`；`PointsBalanceChanged` 仅使缓存失效。

## 8. 幂等、兼容与破坏性变更门禁

同一幂等键、同一 payload/hash 的重试返回原结果；同键异载荷进入冲突/安全隔离。生产端使用事务
Outbox，消费端使用 Inbox，业务入账/发布/分配再以 descriptor 的 `idempotencyKey` 兜底。

schemaVersion 1 内只允许增加可选字段，并须证明旧消费者可忽略。以下任一变化属于破坏性变更：

- 删除字段、把可选改必填、收窄已有枚举或改变金额/时间/主体语义；
- 改 eventType、生产者、aggregate 身份/版本规则或幂等键含义；
- 改变消费者会产生的业务副作用，或把命令伪装成事实；
- 让旧 payload 在新 schema 下表示另一种业务事实。

破坏性变化必须新建 eventType、logical Topic 和 schemaVersion，并提供双写/双读、回放、截止时间和
回滚方案；禁止原地覆盖 `.v1`。CI 在生成前运行：

```ts
const errors = validatePlatformEventContracts();
if (errors.length > 0) throw new Error(errors.join("\n"));
```

校验至少阻止重复 eventType/Topic、错版本后缀、未登记生产者/消费者、audience 漂移、
`eventVersion`、旧 `PUB_CHARGE_RESERVE`、提现主体回退，以及账号分配缺失
`assignmentSnapshotVersion`。

## 9. 不登记为异步 Topic 的同步命令

以下动作仍由 OpenAPI 内部 API 提交，不能为了“全事件化”另造 Topic：库存预占/提交/释放请求、
发货登记、售后/评价决定、发布费预占 API、积分 Quote/Reserve/Commit/Release/Refund、
OPC 提现创建/查单，以及 OPC `session-grants` 创建/撤销/状态查询。HTTP 超时复用原幂等键查单；
同步受理不等于业务终态，终态只认本注册表中对应事实事件。
