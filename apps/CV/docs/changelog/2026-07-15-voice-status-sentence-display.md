# 数字人实时沟通状态栏按句显示改动说明

## 本次优化方案

实时语音播放时，前端原来直接把当前 `tts_audio` 携带的完整 `item.text` 写入状态栏。若上游一次音频里包含多句话，状态栏就会显示一整段长文本，不像正常说话时一句一句呈现。

本次不改后端音频生成、RAG 仲裁、人物记忆或播放队列，只在浏览器播放层优化展示节奏：

1. 在 `voice_turn_policy.js` 增加状态栏语音文本切句策略。
2. 先按 `。！？；` 等句末标点分句。
3. 没有明显句末标点或单句过长时，再按逗号、顿号和最大长度做保底拆分。
4. 播放音频时根据当前播放进度和各句字符长度比例切换状态栏。
5. `index.html` 更新脚本版本号，避免浏览器继续使用旧缓存。

## 主要改动

- `server_deploy/avatar/voice_turn_policy.js`
  - 新增 `speechStatusSegments(text)`。
  - 新增 `speechStatusTextAt(text, progressMs, durationMs)`。

- `server_deploy/avatar/avatar.js`
  - `playNextStreamingAudio()` 不再直接展示完整 `item.text`。
  - 播放开始、`timeupdate` 和进度 watchdog tick 时刷新当前句状态。

- `server_deploy/avatar/index.html`
  - `avatar.js` 与 `voice_turn_policy.js` 版本更新为 `20260715-sentence-status`。

- `server_deploy/avatar/tests/voice_turn_policy.test.js`
  - 增加中文多句切分、长句保底切分、播放进度切换测试。

## Agent1 已执行检查

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`

## Agent2 测试重点

1. 实时沟通中数字人说多句回答时，状态栏应随播放进度显示当前句，而不是一整段回答。
2. 回答没有明显句号但很长时，状态栏也应拆成短段显示。
3. 刷新或重启客户端后应加载 `20260715-sentence-status` 版本脚本。
4. 语音播放、抢话、播放完成上报不应受影响。
