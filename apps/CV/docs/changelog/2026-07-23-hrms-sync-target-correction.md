# 2026-07-23 HRMS 同步目标修正

## 问题

HRMS 管理端刷新考勤缓存显示 0 条，但数字人历史考勤补推到 `hrms.setdx.com` 返回成功。排查发现公网域名和服务器进程存在多套 HRMS 落点，导致数字人写入的 HRMS 与用户查看的 HRMS 不是同一实例。

## 原因

数字人 `.env.server` 使用 `https://hrms.setdx.com`，而当前需要查看考勤的人事系统实例运行在 myserver 同机 `/opt/hrms/app`，端口为 `5183`。公网 Nginx/DNS 存在 `setdx` 与 `shendux` 两套入口，继续依赖公网域名会让同步目标不稳定。

## 修改方案

- 服务器运行配置改为 `HRMS_ATTENDANCE_BASE_URL=http://172.19.0.1:5183`，让数字人 API 容器直接写入同机 HRMS 实例。
- `server_deploy/.env.server.example` 从 `hrms.setdx.com` 改为 `hrms.shendux.com`，避免继续传播旧的 `setdx` 目标。
- 对同机 HRMS 执行历史考勤补推，72 条打卡动作写入成功。

## 影响

- 新产生的数字人考勤会推送到当前 HRMS 实例。
- 已有历史考勤已补推，HRMS 刷新后可聚合为 39 条打卡记录、8 名员工汇总。
- HRMS 员工档案当前仍为 0，考勤记录暂按姓名/前台昵称聚合，尚未绑定 HRMS employeeId。

## 验证

- 数字人 API 健康检查通过。
- 同机 HRMS 健康检查通过。
- HRMS 本地刷新来源为 `frontdesk-cloud-state`，状态记录数为 72，聚合打卡记录数为 39，员工汇总数为 8。
