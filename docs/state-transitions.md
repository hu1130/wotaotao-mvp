# 状态流转说明

状态由后端校验。前端是否展示按钮不构成权限或状态门禁。

## 内容

| 当前状态 | 允许变更为 | 触发操作 |
| --- | --- | --- |
| `DRAFT` | `GENERATED` | AI 生成完成 |
| `GENERATED` | `PENDING_REVIEW` | 商家提交审核 |
| `PENDING_REVIEW` | `APPROVED`、`REJECTED` | 运营通过或驳回 |
| `REJECTED` | `PENDING_REVIEW` | 商家修改后重新提交 |
| `APPROVED` | 无 | MVP 内为终态 |

## 发布

| 当前状态 | 允许变更为 | 触发操作 |
| --- | --- | --- |
| `QUEUED` | `PUBLISHING`、`FAILED` | 发布适配层开始处理或预检失败 |
| `PUBLISHING` | `SUCCEEDED`、`FAILED` | 外部发布回调 |
| `FAILED` | `QUEUED` | 运营人工重试 |
| `SUCCEEDED` | 无 | MVP 内为终态 |

## 询盘

| 当前状态 | 允许变更为 | 触发操作 |
| --- | --- | --- |
| `NEW` | `CONTACTED`、`LOST` | 商家开始联系或关闭无效询盘 |
| `CONTACTED` | `QUOTED`、`LOST` | 商家报价或关闭 |
| `QUOTED` | `WON`、`LOST` | 成交或关闭 |
| `WON`、`LOST` | 无 | MVP 内为终态 |
