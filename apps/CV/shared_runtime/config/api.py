"""外部接口和数字人前端连接配置。"""

import os

from .camera import CAMERA_INDEX
from .common import CACHE_DIR, get_int

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = get_int("API_PORT", 8000)
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
TENANT_API_CREDENTIALS_JSON = os.getenv("TENANT_API_CREDENTIALS_JSON", "").strip()
API_SIGNATURE_TOLERANCE_SECONDS = get_int("API_SIGNATURE_TOLERANCE_SECONDS", 300)
VOICE_TICKET_TTL_SECONDS = get_int("VOICE_TICKET_TTL_SECONDS", 60)
API_CORS_ORIGINS = [
    item.strip()
    for item in os.getenv("API_CORS_ORIGINS", "*").split(",")
    if item.strip()
]
API_CAPTURE_CAMERA_INDEX = get_int("API_CAPTURE_CAMERA_INDEX", CAMERA_INDEX)
API_CAPTURE_WARMUP_FRAMES = get_int("API_CAPTURE_WARMUP_FRAMES", 8)
API_UPLOAD_DIR = os.getenv("API_UPLOAD_DIR") or os.path.join(CACHE_DIR, "api_uploads")

AVATAR_SERVER_URL = os.getenv("AVATAR_SERVER_URL", "http://localhost:3456")
CLIENT_API_ONLY = os.getenv("CLIENT_API_ONLY", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
