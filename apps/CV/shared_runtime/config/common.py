"""配置读取公共工具与项目路径。"""

import os
import re

from core.env_loader import load_dotenv

load_dotenv()


def get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def get_int_pair(name: str, default: tuple[int, int]) -> tuple[int, int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    parts = [part for part in re.split(r"[xX,;\s]+", value.strip()) if part]
    if len(parts) != 2:
        raise ValueError(f"{name} must contain width and height, for example 640x640")
    width, height = (int(parts[0]), int(parts[1]))
    if width <= 0 or height <= 0:
        raise ValueError(f"{name} must be positive, got {width}x{height}")
    return width, height


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMPLOYEES_DIR = os.path.join(BASE_DIR, "employees")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DEVICE_ID = os.getenv("DEVICE_ID", "frontdesk-001")
TENANT_ID = os.getenv("TENANT_ID", "default")
SITE_ID = os.getenv("SITE_ID", "default")
