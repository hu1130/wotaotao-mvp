# 2026-07-22

## 清理状态栏调试提示并修复续播等待文案

### 根因

`avatar.js` 里底部状态栏同时承载语音状态和早期调试状态。`BEHAVIORS.status`、手动表情/动作/口型、模型切换等 `activity` 提示会短暂占用同一个状态框，这些信息对最终前台体验没有必要，也会放大“待机到说话前闪一下”的体感。

另外，数字人被打断后直接续播“刚才我接着说...”时，调用 `playRawTTS()` 没有传 `preparingText`。即使外层先显示等待文案，也会被 `playRawTTS()` 的等待期静默清理覆盖，所以用户看不到“我接着想想哈”。

### 修改

- 移除 `BEHAVIORS.status` 调试文案。
- 移除表情、动作、口型、模型切换对底部状态栏的 `activity` 写入。
- 保留真实语音、识别、思考、错误等 `speech` 状态。
- 直接续播和重新生成两条恢复路径都传入 `preparingText: "我接着想想哈"`。
- 更新 avatar 脚本版本号，避免浏览器沿用旧 `avatar.js`。

### 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
