# 集成分支、环境与版本发布规则

状态：V1.0  
契约主版本：1  
当前引导分支：`integration/full-platform-contracts-v1`  
长期集成分支：`integration`

## 1. 分支拓扑

| 分支/标签 | 生命周期 | 允许内容 | 合并目标 |
| --- | --- | --- | --- |
| `main` | 长期 | 已通过生产门禁的发布快照 | 不接受普通开发 PR |
| `integration` | 长期 | 下一发布候选，所有模块的唯一日常集成点 | `main` |
| `contract/<WBS>-<name>` | 短期 | 公共 API/事件/SDK/Fixture 变更 | `integration` |
| `feat/<WBS>-<name>` | 短期 | 单一业务工作包 | `integration` |
| `fix/<WBS>-<name>` | 短期 | 已复现缺陷及回归测试 | `integration` |
| `release/<version>` | 短期 | 只允许阻塞缺陷、版本和发布说明 | `main`，再回合 `integration` |
| `hotfix/<incident>` | 短期 | 生产事故最小修复 | `main`，再回合 `integration` |
| `contracts-vX.Y.Z` | 永久标签 | 已发布且不可改写的契约基线 | 无 |
| `vX.Y.Z` | 永久标签 | 应用发布版本 | 无 |

本轮已核验远端 `origin/integration` 存在，且 `integration/full-platform-contracts-v1` 基于它完成契约引导。引导分支必须通过 PR 回到真实 `integration`；不得把带斜杠的引导分支长期当作集成分支。仅凭仓库文件不能证明 GitHub 分支保护已经生效，仍须由管理员按第 2 节配置并保留证据。

建议的一次性远端设置：

```bash
git fetch origin
git switch -c integration origin/main
git push -u origin integration
```

若远端已经存在 `integration`，只执行 `git switch --track origin/integration`。创建/保护远端分支由仓库管理员完成，不在开发脚本里自动推送。

## 2. 分支保护

`main` 与 `integration` 必须启用：

- 禁止直接 push、force push 和删除；
- 只允许通过 PR，至少 1 名代码 Owner 批准；高风险模块至少 2 名批准；
- 新提交使旧批准失效，所有对话必须解决；
- 要求分支为最新，要求签名提交按组织策略执行；
- 必需检查：`contract-generated`、`sdk-generated`、`provider-contracts`、`consumer-contracts`、`breaking-change`、`typecheck`、`build`；
- CODEOWNERS 评审必需；管理员不得默认绕过；
- `main` 只接受 `release/*`、`hotfix/*` 或经审批的 `integration` PR。

`.github/CODEOWNERS` 使用 bootstrap 团队名表达所有权。仓库管理员必须先把这些团队映射为真实 GitHub team，并用一次测试 PR 证明自动请求评审有效，才能把 WBS 0.4 标记完成。

## 3. 工作包与 PR 规则

1. 每个任务带 `WBS ID + TPR ID + 分 PRD 功能 ID`；PR 标题以 `[WBS-x.y]` 开头。
2. 一个 PR 只交付一个可验收工作包；超过 3 人日先拆分。
3. 跨系统字段、状态、错误、Topic 或幂等语义必须先走契约 PR。业务 PR 依赖已经发布的契约版本，不混入临时类型。
4. 数据库迁移只由数据 Owner 提交；跨 Owner 修改要有双方批准和从空库/历史库验证。
5. 每日 11:30、18:00 为固定集成窗口。合并者在窗口内更新 `integration`、运行 Smoke、记录结果；其余时间不随意变更公共契约。
6. PR 必须说明完成/未完成范围、输入输出、契约版本、迁移、租户/幂等、开关、测试、回滚、日志/指标和已知限制。
7. 支付、资金、权限、自动发布、外呼、上传、导出至少两人评审，不能自写自批。

## 4. 环境模型

| 环境 | 数据 | 外部系统 | 目的 | 发布方式 |
| --- | --- | --- | --- | --- |
| Local/Dev | 固定合成 Fixture，可随时重建 | Contract Mock 或官方沙箱 | 并行开发、Provider/Consumer 契约测试 | Docker Compose＋本地进程 |
| Integration | 合成数据＋受控测试账户 | Mock 与沙箱均可，必须标记 | 每日跨模块合并与 E2E | `integration` 自动部署 |
| Staging | 脱敏/合成数据，禁止生产库复制 | 官方沙箱或白名单测试账户 | 发布候选、迁移、回滚、容量验证 | `release/*` 不可变制品 |
| Production | 真实数据 | 生产 Provider | 白名单、灰度和正式服务 | 已签名镜像/制品，人工批准 |

Dev Compose 位于 `infra/dev/compose.yaml`，提供 PostgreSQL 16、Redis 7 和全平台 Contract Mock。默认端口：PostgreSQL `55442`、Redis `56379`、Mock `4011`。端口可通过 `.env` 覆盖。所有服务必须有健康检查，数据库和缓存使用命名卷；Mock 每次启动都从版本化合成 Fixture 建立确定状态。

`.env.example` 只包含本地占位值。Staging/Prod 的密码、API Key、回调验签密钥和证书必须由秘密管理系统注入，不得写入 Compose、Git、镜像层或构建日志。

## 5. 契约到实现的发布顺序

所有跨系统升级严格按以下顺序，不能把 Provider 和 Consumer 的不兼容实现一次性同时上线：

```text
1. Contract 向后兼容发布
2. Provider 兼容旧版+新版并先部署
3. 生成/发布 SDK
4. Consumer 分批升级
5. 观测旧字段/旧版本使用量归零
6. 公告弃用并度过支持窗口
7. 新主版本移除旧能力
```

### 5.1 兼容变更

1. 合并契约 PR，CI 生成 `@wotao/platform-sdk` 并打 `contracts-vX.Y.Z`。
2. Provider 在不破坏旧请求/事件的情况下实现新能力，先部署 Dev/Integration，再部署 Staging。
3. Provider 契约测试、幂等、租户隔离和观测通过后，Consumer 才升级 SDK。
4. Consumer 使用功能开关逐个启用；失败时只回滚 Consumer/开关，不回滚已经兼容旧版的 Provider。

### 5.2 破坏性变更

1. 新建 `/v2` operation、`.v2` Topic 或新主版本 Schema；v1 保持可用。
2. Provider 双写/双读或提供 v1→v2 适配，输出必须可观测并可独立关闭。
3. 所有 Consumer 升级到 v2，Owner 在迁移清单逐一签字。
4. v1 至少经过一个正式发布周期和约定弃用窗口；资金/账本/审计数据还须满足法定与追责保留期。
5. 指标证明 v1 连续 14 天无调用/消费、死信为 0、重放通过后，提交单独移除 PR。
6. 删除只发生在下一个契约主版本；禁止在 minor/patch 中通过“临时兼容”绕过门禁。

## 6. 跨仓升级顺序

若后续拆为多个生产仓库，升级批次固定为：

| 批次 | 仓库/服务 | 原因 |
| --- | --- | --- |
| 0 | Contracts/SDK | 先发布唯一事实源和可解析客户端 |
| 1 | Core Provider | 身份、权限、账本、CRM、内容、事件基础能力先兼容 |
| 2 | Marketplace Provider/Consumer | 商品、订单、支付先可输出稳定事实，再消费 Core 能力 |
| 3 | Automation Provider/Consumer | 发布、外呼、微信、OPC 依赖身份、额度和业务对象 |
| 4 | Analytics Consumer | 最后消费稳定事实；不得反向成为交易事实源 |
| 5 | Web/H5/BFF Consumer | 后端兼容完成后再逐步启用界面能力 |

同一批次内部可以并行，但下游不得在上游 Provider 尚未部署时打开功能开关。跨仓 release manifest 必须记录仓库、提交 SHA、镜像 digest、契约版本、迁移版本和开关默认值。

## 7. 版本矩阵

每个发布候选在 `docs/releases/<version>.md` 固化下表；未填写不得升 Staging：

| 制品 | 当前版本/SHA | 目标版本/SHA | 最低兼容版本 | Owner | 回滚目标 |
| --- | --- | --- | --- | --- | --- |
| Contracts | 待填 | 待填 | 待填 | DEV-B | 待填 |
| Platform SDK | 待填 | 待填 | 待填 | DEV-B | 待填 |
| Core | 待填 | 待填 | 待填 | DEV-B | 待填 |
| Marketplace | 待填 | 待填 | 待填 | DEV-C | 待填 |
| Automation | 待填 | 待填 | 待填 | DEV-E | 待填 |
| Analytics | 待填 | 待填 | 待填 | DEV-F | 待填 |
| Web/H5 | 待填 | 待填 | 待填 | DEV-A | 待填 |

## 8. 发布流水线与门禁

### Gate C0：Contract Ready

- 规范、Schema、Topic、错误、幂等、样例、Fixture 和 SDK 一致；
- Provider/Consumer 契约测试与破坏性比较通过；
- 版本、Owner、影响方和弃用计划齐全。

### Gate C1：Integration Ready

- 从空库可迁移，合成数据可重复加载；
- `pnpm typecheck`、测试、build 全绿；
- 核心调用、重复请求/事件、越权、失败与恢复通过；
- Console、关键网络、日志和死信无未解释错误。

### Gate C2：Staging Ready

- 12 条跨系统 E2E 通过；支付/退款/发布等条件能力使用真实沙箱或白名单证据；
- 备份恢复、迁移回滚/前滚、100 次事件重放、账本重建和对账通过；
- 桌面端、移动端、刷新持久化、限流和权限反例通过；
- 镜像/SBOM/秘密/漏洞扫描通过，Mock 地址和开发请求头未进入生产配置。

### Gate C3：Production Ready

- 发布清单、变更窗口、值守、告警、开关、灰度人群和回滚 Owner 已批准；
- 数据库先执行兼容的 expand 迁移，应用灰度后才 contract；
- 先内部账户，再企业白名单，再分批扩大；每批观察关键 SLI 后继续；
- 任一账本不平、重复扣款/发布、串户、回调验签失败或不可恢复 UNKNOWN 立即停止扩大。

## 9. 回滚规则

- 应用使用上一不可变镜像回滚；不得在服务器现场改代码。
- 数据库使用 expand/contract：先加新结构并双写，确认所有旧版本退出后才删除；有损迁移只能前滚修复，不能盲目降级。
- 事件不能“撤回”；错误事实用补偿事件修正，保留原事件和审计链。
- SDK/Contract 不覆盖已发布版本。Consumer 回滚到仍受 Provider 支持的版本。
- 外部副作用失败时先查单；状态未知不得直接重试创建第二笔支付、作品、外呼或提现。
- 回滚后必须重跑 Smoke、核对死信/Outbox/Inbox、资金差异和租户隔离。

## 10. 发布节奏与完成证据

- 每日：11:30、18:00 集成；窗口后发布一份 Smoke 结果。
- 每周：冻结一个可部署候选，更新契约基线、版本矩阵和未决风险。
- 正式发布：使用 `release/<version>`；D4/发布冻结后不加新功能，只修 P0/P1。
- 首周值守：每次告警有 Owner、处置时间、影响、恢复和复盘链接。

WBS 0.4 的完成证据包括真实 `integration` 远端分支、保护规则截图/导出、一次 CODEOWNERS 测试 PR 和权限表；仅提交本文不等于远端配置完成。WBS 0.6/9.2 的完成证据包括 Dev Compose 健康、Integration/Staging 部署记录、无真实秘密扫描和一次回滚演练。
