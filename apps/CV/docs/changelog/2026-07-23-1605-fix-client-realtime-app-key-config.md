# 2026-07-23

## 问题

重新打包 Windows 客户端后，双击 `CVClient.exe` 在启动阶段弹出 PyInstaller 未处理异常：
`ImportError: cannot import name 'REALTIME_DIALOG_APP_KEY' from 'config'`。

## 原因

7 月 22 日 realtime dialog 授权修复把共享语音模块 `shared_runtime/core/fixed_tts.py`
和 `shared_runtime/core/realtime_dialog.py` 改为从顶层 `config` 导入
`REALTIME_DIALOG_APP_KEY`。服务端配置已同步该字段，但客户端
`client_deploy/config/voice.py` 没有导出同名配置。客户端打包后使用
`client_deploy/config` 作为顶层配置包，因此共享语音模块在导入阶段失败，业务逻辑尚未启动。

## 修改方案

- `client_deploy/config/voice.py` 补齐 `REALTIME_DIALOG_APP_KEY` 配置导出，默认从环境变量读取，未配置时为空。
- 客户端 env 示例和 `build-client-exe.ps1` 生成的 `.env` 模板同步空配置项，避免真实密钥写入客户端安装包。
- 增加客户端配置契约回归测试，覆盖共享 `fixed_tts` 在客户端配置下可正常导入。

## 影响

影响 Windows 客户端启动和打包配置。不会改变录脸任务、签到签退、远程识别或服务器 realtime dialog 凭证。

## 验证

- `PYTHONPATH=client_deploy;shared_runtime python -c "import core.fixed_tts; print('ok')"`
- `PYTHONPATH=client_deploy;shared_runtime python -m unittest client_deploy.tests.test_client_config_contract`
