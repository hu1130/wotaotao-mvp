# 企业文档增量索引优化方案

## 背景

企业文档每次更新后，控制台默认“清空旧索引”，后端即使不清空也会重新读取所有文档、重新切块并重新调用 embedding，导致已有未变化文档重复处理，浪费时间和 embedding 成本。

## 修改方案

1. `knowledge_documents` 增加索引元数据：
   - `content_hash`
   - `content_bytes`
   - `indexed_at`
2. 索引前先枚举允许目录内的文档文件，并按原始文件内容计算 SHA256。
3. 非强制重建时，先查询数据库中同租户、同路径的 `content_hash`：
   - hash 一致：跳过，不解析、不切块、不调用 embedding。
   - hash 不一致或数据库不存在：重新解析、切块、embedding 并替换该文档旧 chunks。
4. 增量索引会删除当前索引范围内已经不存在的文档记录，避免删除文件后仍被检索到。
5. 控制台默认从“重建索引 + 清空旧索引”改为“更新索引 + 增量更新”，保留“强制全量重建”复选框用于回退。

## 注意事项

- 部署后第一次增量索引时，历史 `knowledge_documents` 没有 `content_hash`，所以会重新索引一次并补齐指纹；第二次开始才会明显跳过未变化文档。
- `reset=true` 仍会清空当前租户全部知识索引，然后全量重建。
- 删除文档后执行增量更新，会清理该文档对应索引。

## 本地验证

已执行：

```powershell
$env:PYTHONPATH='D:\CV_deploy\dist_deploy\server_deploy;D:\CV_deploy\dist_deploy\shared_runtime'; python -m unittest server_deploy.tests.test_knowledge_incremental_index -v
python -m py_compile server_deploy\core\knowledge\service.py shared_runtime\core\knowledge\store.py server_deploy\tests\test_knowledge_incremental_index.py
node --check server_deploy\avatar\control.js
```

## 服务器验证

已同步并重建：

- `/opt/server_deploy/core/knowledge/service.py`
- `/opt/shared_runtime/core/knowledge/store.py`
- `/opt/server_deploy/avatar/control.html`
- `/opt/server_deploy/avatar/control.js`
- `/opt/server_deploy/tests/test_knowledge_incremental_index.py`

已执行：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml build api avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api python -m py_compile core/knowledge/service.py core/knowledge/store.py tests/test_knowledge_incremental_index.py
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T api sh -c "PYTHONPATH=/app python -m unittest tests.test_knowledge_incremental_index -v"
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T avatar node --check control.js
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/healthz
```

已确认 `knowledge_documents` 存在新列：

- `content_hash`
- `content_bytes`
- `indexed_at`

## Agent2 建议测试

1. 上传两个企业文档后点击“更新索引”，首次应索引所有文档。
2. 不修改文档再次点击“更新索引”，返回结果应显示 `skippedDocuments` 大于 0，`indexedDocuments` 为 0 或只包含实际变化文件。
3. 修改其中一个文档后点击“更新索引”，只应重建该文档。
4. 删除一个文档后点击“更新索引”，`removedDocuments` 应增加，检索不再命中被删文档。
5. 勾选“强制全量重建”后点击“更新索引”，应仍能完整重建。

## 回退方式

如果现场需要恢复旧行为，控制台勾选“强制全量重建”即可；代码层无需回滚。
