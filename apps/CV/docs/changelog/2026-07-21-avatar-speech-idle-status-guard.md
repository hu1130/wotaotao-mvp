# 2026-07-21 数字人播报状态防提前待机

## 问题

数字人语音还没播完时，状态栏可能提前清空或回到“待机中”，用户会看到语音仍在播放但页面状态已经像空闲。

## 原因

前端旧的 `scheduleIdle()` 定时器在流式语音开始后没有统一取消，`enterIdle()` 自身也没有检查当前是否仍在监听、思考、排队或播放音频。只要旧定时器到点，就可能把 `statusMode` 改回 idle 并显示“待机中”。另外说话阶段音频先到、文本尚未回填时，`statusText('speaking')` 返回空字符串，容易放大状态栏消失的观感。

## 修改方案

- `showStatus(..., 'speech')` 会取消旧 idle 定时器，防止语音状态被历史定时器覆盖。
- `enterIdle()` 增加语音活动守卫：监听中、对话忙、流式音频播放或排队、普通音频播放、非实时对话语音优先级占用时，拒绝切到待机并记录客户端日志；实时对话结束后的本地释放宽限期不阻止状态正常回到待机。
- 说话阶段没有可展示文本时返回“叮当正在说话”，避免状态栏空白。
- 更新 avatar 前端脚本版本号，避免浏览器继续使用旧缓存。

## 验证

- 已通过：`node --check server_deploy/avatar/avatar.js`
- 已通过：`node --check server_deploy/avatar/voice_turn_policy.js`
- 已通过：`node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
