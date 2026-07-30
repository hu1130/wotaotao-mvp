# MVP 接口权限矩阵

`x-role` 表示当前角色；商家请求还必须携带 `x-merchant-id`。商家资源查询始终按该商家 ID 隔离。

| 接口 | 商家 | 运营人员 | 买家/公开 |
| --- | --- | --- | --- |
| `POST /products` | 创建自己的商品 | 禁止 | 禁止 |
| `GET /products/{id}` | 仅自己的商品 | 只读 | 仅公开商品 |
| `POST /contents/generate` | 基于自己的商品生成 | 禁止 | 禁止 |
| `PUT /contents/{id}` | 修改自己的可编辑内容 | 禁止 | 禁止 |
| `POST /contents/{id}/submit-review` | 提交自己的内容 | 禁止 | 禁止 |
| `GET /reviews/pending` | 禁止 | 只读 | 禁止 |
| `POST /reviews/{id}/approve` | 禁止 | 允许并留痕 | 禁止 |
| `POST /reviews/{id}/reject` | 禁止 | 允许并留痕 | 禁止 |
| `GET /authorized-accounts` | 禁止 | 仅返回脱敏引用 | 禁止 |
| `POST /publications` | 禁止 | 允许并留痕 | 禁止 |
| `POST /publications/callback` | 禁止 | 可信发布系统 | 禁止 |
| `POST /publications/{id}/retry` | 禁止 | 允许并留痕 | 禁止 |
| `GET /feed` | 公开 | 公开 | 公开 |
| `GET /storefront/products/{id}` | 公开 | 公开 | 公开 |
| `POST /inquiries` | 禁止 | 禁止 | 买家创建 |
| `GET /merchant/inquiries` | 仅自己的询盘 | 按指定商家只读 | 禁止 |
| `PATCH /inquiries/{id}/status` | 更新自己的询盘 | 只读，禁止修改 | 禁止 |
