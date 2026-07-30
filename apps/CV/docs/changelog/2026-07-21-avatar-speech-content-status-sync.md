# 2026-07-21 数字人说话状态栏同步内容

## 问题

数字人播放回答时，底部状态栏显示的是固定状态文案 `叮当正在说话`，没有同步当前正在说的回答内容。播放结束后，部分路径还会写回 `待机中` 或 `我在听，你直接说话`，容易造成用户看到的状态文字和真实播放状态不一致。

## 根因

- 流式播放路径 `updateStreamingSpeechStatus()` 只调用 `voiceTurnPolicy.statusText('speaking')`，没有传入当前音频对应的文本，因此只能得到固定 speaking 文案。
- 固定话术和原始 TTS 播放路径在音频结束时会写入待机提示，而不是统一清空底部状态和语音文本。
- 服务端 `done: ok` 回调会在音频播放协调之外写入完成文案，和播放中的字幕式状态存在竞争。

## 修改

- `speaking` 状态不再提供默认的 `叮当正在说话` 文案；只有传入文本时才显示内容。
- 流式回答、固定话术、原始 TTS 都基于 `audio.currentTime` 和音频时长调用 `speechStatusTextAt()`，按一到两句粒度显示当前正在说的内容。
- 原始 TTS 在音频加载阶段也只显示首个短句，避免播放开始前先把整段回答铺到状态栏。
- `avatar.js` 将当前 speech 状态栏文本提升为 `speechStatusText` 并通过 `STATE_SYNC` 同步给父页面和控制端。
- 漩涡外层 `voice-orb.tsx` 优先使用 `speechStatusText` 作为底部栏文案，避免只根据 `speaking` phase 显示“正在说话”。
- 数字人说完或播放出错后统一清空底部状态栏、语音文本和助手字幕，避免残留 `待机中` 或旧回答。
- 正常 `done: ok` 不再额外写入“回答完成”，只保留异常结束原因的提示。

## 影响

- 签到、签退、repeat、arrival_task 的固定话术播放入口未改回排队或缓存逻辑，仍保留当前可直接播放的行为。
- 状态栏现在更像真人实时字幕：播放中显示短句内容，播放结束及时回到空状态。

## 验证

```powershell
node --check server_deploy/avatar/avatar.js
node --check server_deploy/avatar/voice_turn_policy.js
node --test server_deploy/avatar/tests/voice_turn_policy.test.js
node .\node_modules\next\dist\bin\next build
```

结果：语法检查通过，avatar 语音策略测试 14 条通过，漩涡 Next 静态构建通过，并已覆盖复制到 `server_deploy/avatar/imported-ui`。
