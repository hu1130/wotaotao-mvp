# 2026-07-20

## 问题

超级管理员客户端详情弹窗里重复放了“新增激活码”和“删除客户端”按钮，而客户端列表行内已经有相同操作。激活码详情只显示前缀，未使用激活码无法在详情中查看完整码并复制。

## 原因

详情弹窗沿用了原页面展开区的操作按钮，导致操作入口重复。设备激活码原先只保存 `code_hash` 和 `code_prefix`，历史详情接口没有完整激活码可返回，前端无法展示真实完整码。

## 修改方案

- 移除客户端详情弹窗内的“新增激活码”和“删除客户端”按钮，保留列表行内操作。
- `device_activation_codes` 新增 `activation_code` 字段，新建激活码时保存完整码。
- 设备成功领取激活码时清空 `activation_code`，避免已使用码继续暴露。
- 平台详情接口仅对未使用且仍有完整码的记录返回 `activationCode`。
- 超级管理员激活码列表默认隐藏完整码，点击小眼睛查看，点击复制按钮复制完整码。

## 影响

影响超级管理员客户端详情、平台激活码列表接口和设备激活码持久化。旧激活码历史上只保存 hash，无法反推完整码；只有变更后新建且未使用的激活码可查看完整值。

## 验证

- 运行 `python -m unittest tests.test_client_admin_service`。
- 运行 `python -m py_compile core/device_identity/models.py core/device_identity/repository.py core/client_admin/service.py`。
- 运行 `node --check avatar/super-admin.js`。
