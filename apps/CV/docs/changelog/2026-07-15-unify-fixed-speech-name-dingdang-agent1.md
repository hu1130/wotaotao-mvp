# Agent1 交付：固定语录称呼统一为叮当

## 问题现象

固定语录和部分前端切换话术仍会出现“小E”称呼，用户要求统一改为“叮当”。

## 根因

“小E”存在于三类位置：

1. 角色默认 profile：`shared_runtime/config/profiles.py`
2. 当前服务器运行环境变量：`/opt/server_deploy/.env.server`
3. 已生成的每日语录缓存：`/opt/server_deploy/cache/daily_tts_texts.json`
4. 前端模型切换话术：`server_deploy/avatar/avatar.js`

只改源码默认值不能影响已经生成的每日语录缓存，因此本次同步处理运行缓存。

## 修改方案

- Epsilon 默认 `bot_name` 从 `小E` 改为 `叮当`。
- Epsilon 默认角色描述从“小E”改为“前台数字人叮当”。
- 服务器 `.env.server` 中 `MODEL_BOT_NAME_EPSILON` 和 `MODEL_ROLE_EPSILON` 同步改为叮当。
- 前端模型切换 handoff 文案从“小E接棒啦”改为“叮当接棒啦”。
- 服务器当前 `daily_tts_texts.json` 中所有 `小E/小e` 替换为 `叮当`。

## 修改文件

- `shared_runtime/config/profiles.py`
- `server_deploy/avatar/avatar.js`
- `server_deploy/.env.server`

## 服务器同步与验证

已同步：

- `shared_runtime/config/profiles.py` -> `/opt/shared_runtime/config/`
- `server_deploy/avatar/avatar.js` -> `/opt/server_deploy/avatar/`
- `server_deploy/.env.server` -> `/opt/server_deploy/`

已处理服务器缓存：

```text
/opt/server_deploy/cache/daily_tts_texts.json
```

已重建并重启：

```bash
docker compose --env-file .env.server -f docker-compose.deploy.yml build api avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d api avatar memory-worker
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
```

验证结果：

- `MODEL_PROFILES['epsilon']['bot_name'] == '叮当'`
- 运行相关路径 `/opt/server_deploy/avatar`、`/opt/shared_runtime/config`、`/opt/server_deploy/cache/daily_tts_texts.json`、`/opt/server_deploy/.env.server` 已搜不到 `小E/小e`
- `node --check avatar.js` 通过
- `/health` 通过
- `/healthz` 通过
- API、avatar、nginx 均 healthy

## 注意

浏览器可能缓存旧 `avatar.js`。如果前台页面仍显示旧切换话术，刷新数字人页面或重启客户端窗口即可加载新文件。
