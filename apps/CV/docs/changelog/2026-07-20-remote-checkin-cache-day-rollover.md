# API-only 客户端签到缓存跨天重置修复

## 问题现象

API-only 客户端进程跨夜不重启时，用户前一天签退后，客户端本地 `RemoteCheckInStore` 仍可能保留 `_checked_out` 缓存。第二天点击签退按钮或本地状态判断时，可能继续提示“今日已签退”，没有重新向服务端确认当天记录。

服务端权威签到链路本身按 `date.today()` 查询 MySQL，并且 Redis 签到/签退 key 带日期；问题集中在客户端本地 facade 缺少日期维度。

## 根因

`RemoteCheckInStore` 只缓存姓名集合：

- `_checked_in`
- `_checked_out`
- `_today_count`

这些缓存没有记录所属日期，也没有跨天清空逻辑。与 `RedisCheckIn._reset_local_if_new_day()` 相比，API-only 客户端 facade 少了同等保护。

## 修改

- 为 `RemoteCheckInStore` 增加 `_local_date` 与 `_reset_local_if_new_day()`。
- 在 `update_from_frame()`、`is_checked_in_today()`、`is_checked_out_today()`、`get_today_count()` 和 `_refresh_name()` 入口执行跨天检查。
- 新增 `mark_checked_out()`，签退成功后通过统一方法更新本地缓存，避免调用方直接写内部集合。
- 同步更新 `client_deploy/core/remote_recognition.py` 与 `server_deploy/core/remote_recognition.py` 中的同名实现。

## 验证

- 新增单元测试覆盖：昨天已签退并有今日人数缓存，日期切到第二天后，签退/签到缓存与今日人数均清零，并重新按服务端当天记录判断。
- 执行 Python 编译检查覆盖两个实现文件。
