# 2026-07-21 漩涡回答字幕稳定性修复

## 问题

漩涡前台回答时，底部状态栏会先显示文本，随后短暂切换成只有音律动画，再切回文本。

## 原因

导入版漩涡前台的底部状态组件只读取 `assistantSpeechText` 和 `visitorSpeechText`。数字人运行时在回答播放过程中用于“一到两句”滚动展示的字段是 `voiceChatText`，因此当 `assistantSpeechText` 在流式状态同步中暂时为空时，前台会误判为无文字，只展示音律动画。

## 修改方案

`frontend_sources/imported-vortex-frontdesk/components/voice-controls.tsx` 调整字幕选择规则：

- 回答中优先展示 `voiceChatText`，没有时再使用 `assistantSpeechText`。
- 倾听时优先展示访客识别文本。
- 状态栏增加独立字幕稳定层，有新文本就更新，短暂空状态不立刻清空，避免闪成纯音律。
- 进入真正空闲后通过 900ms 清空确认窗口移除旧字幕，避免说完后继续显示旧内容。
- 即使运行时在 `speaking`、`understanding`、`ready` 之间短暂抖动，只要仍有 `voiceChatText` 就继续按助手字幕展示。

## 影响

只影响导入版漩涡前台的底部状态栏展示逻辑，不改变 ASR、LLM、TTS、播放队列和数字人状态机。

## 验证

已执行前台构建，并同步构建产物到运行目录。服务器同步后需重建 `avatar` 容器并检查健康接口。
