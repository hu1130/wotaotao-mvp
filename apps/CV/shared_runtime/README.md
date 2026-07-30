# Shared Runtime

This directory is the single source of truth for Python modules used by both
`server_deploy` and `client_deploy`.

## Layering model

1. `shared_runtime/` provides role-neutral `config/` and `core/` modules.
2. `server_deploy/` and `client_deploy/` contain entry points and modules whose
   behavior genuinely differs by role.
3. Local source runs extend the role package path to this directory.
4. Docker and PyInstaller builds materialize the shared layer first and overlay
   the selected role layer on top.

Do not copy a shared module back into both role directories. If behavior must
diverge, keep the common mechanism here and add a small role adapter in the
appropriate deployment directory.

Intentional same-path role implementations are documented in
`role_overrides.json`. Any new override requires an explicit reason and must
pass:

```powershell
python .\scripts\check-runtime-boundaries.py
```

Create a server deployment bundle with repository-shaped `shared_runtime/` and
`server_deploy/` directories:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\materialize-runtime.ps1 `
  -Role server `
  -Destination D:\CV_deploy\server_deploy_bundle `
  -Force `
  -IncludeEnvironment
```

The client build script uses the same materializer in overlay mode, producing a
single staged source tree for PyInstaller.
