"""项目配置公共导出。

调用方继续使用 ``from config import XXX``，具体配置按领域拆分到子模块。
"""

from pathlib import Path as _Path


def _extend_shared_config_path() -> None:
    for parent in _Path(__file__).resolve().parents:
        candidate = parent / "shared_runtime" / "config"
        if candidate.is_dir():
            candidate_text = str(candidate)
            if candidate_text not in __path__:
                __path__.append(candidate_text)
            return


_extend_shared_config_path()

from . import (  # noqa: E402
    api,
    camera,
    common,
    concurrency,
    database,
    device_identity,
    gesture,
    hrms_sync,
    knowledge,
    person_memory,
    profiles,
    tenant_admin,
    voice,
)

_EXPORT_MODULES = (
    common,
    camera,
    database,
    device_identity,
    hrms_sync,
    api,
    profiles,
    knowledge,
    voice,
    gesture,
    person_memory,
    concurrency,
    tenant_admin,
)

for _module in _EXPORT_MODULES:
    for _name in dir(_module):
        if _name.isupper() or _name == "get_model_profile":
            globals()[_name] = getattr(_module, _name)

__all__ = sorted(
    name
    for name in globals()
    if name.isupper() or name == "get_model_profile"
)

del _module, _name, _extend_shared_config_path
