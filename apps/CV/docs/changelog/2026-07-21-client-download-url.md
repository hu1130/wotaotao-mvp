# 2026-07-21 客户端直接下载地址

## 问题

当前 Windows 客户端只能通过人工复制 `CVClient` 目录分发。用户希望提供一个浏览器可直接输入的下载网址，方便现场安装。

## 原因

项目打包产物不是单个 `CVClient.exe`，运行时还依赖同目录的 `_internal/`、`.env` 和停止脚本。直接下载 exe 会导致客户端无法完整运行，因此需要发布整个 `CVClient` 目录的压缩包。

## 修改方案

- 在 avatar 服务新增公开下载路由：
  - `/download/client`
  - `/download/client.zip`
- 下载文件固定读取 `cache/downloads/CVClient.zip`，该目录已通过 docker compose 挂载到容器内，不需要把 800MB 级安装包打进镜像。
- 下载响应使用附件形式返回 `CVClient.zip`，浏览器输入地址即可开始下载。
- 生成当前客户端压缩包，排除外层 `CVClient/cache/` 运行日志目录。

## 影响

只新增客户端安装包下载入口，不影响控制台鉴权、avatar 展示、语音链路、设备激活和客户端运行逻辑。下载包内仍包含当前打包产物自带的 `.env`，新设备首次启动仍按现有激活流程绑定租户和设备。

## 验证

- `node --check server_deploy/avatar/server.js`
- 本地生成 `D:\CV_deploy\client_downloads\CVClient.zip`
- 抽查 zip 包含 `CVClient/CVClient.exe` 和 `CVClient/_internal/`
- 抽查 zip 不包含外层 `CVClient/cache/`
