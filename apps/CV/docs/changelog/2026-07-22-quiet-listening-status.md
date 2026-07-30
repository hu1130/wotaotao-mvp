# 2026-07-22

## 避免待机到说话前状态栏闪烁

### 根因

前端在自动 VAD 触发 `startVoiceTurn()` 时会立即显示底部状态栏“我在听呢”。如果这次监听来自环境声或很快被固定语音/恢复播放接管，状态栏会先出现再被清理，看起来像待机和数字人说话前闪一下。

恢复被打断回答的路径也仍然直接调用 `showStatus('', 'idle')` 清理状态栏，会参与同样的显示/隐藏链路。

### 修改

- 自动监听刚开始时不再弹出底部状态栏，只保留内部 voice phase 和控制端文本。
- 服务端默认 `listening` 事件没有显式文案时，不再显示底部状态栏。
- 恢复被打断回答前改为静默清理状态。
- 空插话后重新生成上一句时，等待文案改为 `我接着想想哈~`。
- 更新 avatar 脚本版本号，避免浏览器沿用旧代码。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
