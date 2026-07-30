# Auto Incremental Knowledge Index

## 问题

控制台企业文档上传或删除成功后，只刷新了文档列表并提示用户手动重建索引。现场容易忘记点击“更新索引”，导致 RAG 仍使用旧索引。

## 原因

已有增量索引能力只绑定在手动“更新索引”按钮上，文档变更事件没有自动提交索引任务。

## 修改方案

- 控制台抽出通用 `startKnowledgeIndex(reset, source)`。
- 手动“更新索引”继续读取“强制全量重建”复选框。
- 文档上传成功后自动调用 `startKnowledgeIndex(false, 'document_upload')`。
- 文档删除成功后自动调用 `startKnowledgeIndex(false, 'document_delete')`。
- 自动触发固定使用 `reset=false`，只走已有 content hash 增量索引，未变化文档会跳过，删除文件会清理对应索引。
- 如果已有索引任务运行中，控制台不重复提交，改为继续轮询当前任务。

## 影响

仅影响控制台企业文档上传/删除后的自动索引提交，不改变后端增量索引算法、手动全量重建入口、检索或租户隔离。

## 验证

- `node --check server_deploy/avatar/control.js`
- `npm test` in `server_deploy/avatar`
