# 2026-07-21 yourvoice.shendux.com 绑定 videoagent

## 问题

`yourvoice.shendux.com` 已解析到当前服务器 `8.140.35.121`，但服务器 80 端口由 CV 项目的入口 Nginx 占用，直接访问域名会落到 CV 数字人项目首页，而不是服务器上的 `videoagent` 项目。

## 原因

`videoagent` 自己的 Nginx 暴露在宿主机 `5002` 端口，移动端入口为 `/mobile/`。DNS 只能解析到 IP，不能指定端口和路径；因此需要入口 Nginx 根据 Host 将 `yourvoice.shendux.com` 代理到宿主机 `5002`。

## 修改方案

- 在入口 Nginx 配置中新增 `server_name yourvoice.shendux.com` 的 vhost。
- 根路径 `/` 跳转到 `/mobile/`。
- 其余路径代理到 `http://172.17.0.1:5002`，由 `videoagent-nginx` 继续处理 `/mobile/`、`/desktop/`、`/api/` 等路由。

## 影响

只影响 `yourvoice.shendux.com` 这个域名。默认 IP 访问和 CV 数字人项目原有路由保持不变。`videoagent` 业务容器、数据库和 Redis 不重启。

## 验证

- `nslookup yourvoice.shendux.com` 返回 `8.140.35.121`
- `curl -I http://8.140.35.121:5002/mobile/` 返回 `200`
- `nginx -t` 通过
- `curl -I http://yourvoice.shendux.com/` 返回 `302 /mobile/`
- `curl -I http://yourvoice.shendux.com/mobile/` 返回 `200`
- `curl http://127.0.0.1/health` 和 `curl http://127.0.0.1/healthz` 正常，确认默认 IP 入口仍回到 CV 项目
