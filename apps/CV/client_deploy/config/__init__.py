"""项目配置公共导出。

调用方继续使用 ``from config import XXX``，具体配置按领域拆分到子模块。
"""

from pathlib import Path


def _extend_shared_config_path() -> None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "shared_runtime" / "config"
        if candidate.is_dir():
            candidate_text = str(candidate)
            if candidate_text not in __path__:
                __path__.append(candidate_text)
            return


_extend_shared_config_path()

from . import api, camera, common, database, gesture, hrms_sync, knowledge, profiles, voice

_EXPORT_MODULES = (
    common,
    camera,
    database,
    api,
    profiles,
    knowledge,
    voice,
    gesture,
    hrms_sync,
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

del _module, _name, _extend_shared_config_path, Path
