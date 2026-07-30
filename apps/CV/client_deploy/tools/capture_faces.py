"""人脸注册拍照工具: 正脸/左脸/右脸 各3张, 共9张, 录入 pgvector"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    AVATAR_SERVER_URL,
    CAMERA_INDEX,
    EMPLOYEES_DIR,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    TENANT_ID,
)
from core.camera_control import (
    clear_camera_pause,
    request_camera_pause,
    wait_for_camera_released,
)
from core.insightface_factory import create_face_analysis
from core.employee_names import normalize_employee_name, tenant_employee_directory
from core.shutdown import is_shutdown_requested
from core.api_client import ApiClientError, SignedApiClient
from core.vector_db import VectorDB
from core.env_loader import load_dotenv

import logging
import argparse
import hashlib
import hmac
import json
import platform
import shutil
import time
from urllib.parse import urlparse
import urllib.error
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("capture")

ANGLES = [
    ("zheng", "请正对摄像头"),
    ("zuo", "请缓慢转向左侧"),
    ("you", "请缓慢转向右侧"),
]
PHOTOS_PER_ANGLE = 3
TOTAL_PHOTOS = len(ANGLES) * PHOTOS_PER_ANGLE
DETECT_EVERY_N = 5
ANGLE_READY_SECONDS = 2.0
AUTO_CAPTURE_INTERVAL_SECONDS = 0.8
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
ENABLE_TTS_PREWARM = os.environ.get("ENABLE_TTS_PREWARM") == "1"
ENROLL_VIA_API = os.environ.get("FACE_CAPTURE_ENROLL_VIA_API", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
} or os.environ.get("CLIENT_API_ONLY", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WINDOW_TOPMOST_RETRY_SECONDS = 1.5

_FONT_PATH = None
for _fp in [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]:
    if os.path.exists(_fp):
        _FONT_PATH = _fp
        break


def _pil_text(img: np.ndarray, text: str, pos: tuple, size: int, color: tuple) -> None:
    if _FONT_PATH is None:
        cv2.putText(
            img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, size / 20, color, 1, cv2.LINE_AA
        )
        return
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.truetype(_FONT_PATH, size)
    draw.text(pos, text, font=font, fill=color)
    rgb = np.array(pil_img)
    img[:] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def draw_guide(
    frame: np.ndarray,
    angle_name: str,
    hint: str,
    count: int,
    total: int,
    angle_count: int,
    next_capture_in: float,
) -> None:
    h, w = frame.shape[:2]
    bar_h = 70
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    cv2.line(frame, (0, bar_h), (w, bar_h), (48, 194, 242), 1, lineType=cv2.LINE_AA)
    _pil_text(frame, f"注册人脸 · {angle_name}", (15, 12), 20, (245, 245, 245))
    _pil_text(frame, f"进度: {count}/{total} 张", (15, 40), 18, (48, 194, 242))
    _pil_text(frame, hint, (w // 2 - 130, h // 2 + 10), 28, (48, 194, 242))
    if next_capture_in > 0:
        status = f"请保持姿势，{next_capture_in:.1f}s 后自动拍摄"
    else:
        status = f"自动拍摄中: {angle_count}/{PHOTOS_PER_ANGLE}"
    _pil_text(frame, status, (w // 2 - 180, h // 2 + 50), 22, (100, 215, 90))
    _pil_text(
        frame,
        "自动连拍，无需按空格 | Q 退出",
        (w // 2 - 160, h - 30),
        18,
        (160, 160, 160),
    )


def draw_done(frame: np.ndarray) -> None:
    h, w = frame.shape[:2]
    _pil_text(
        frame,
        "全部拍摄完成! 按任意键退出",
        (w // 2 - 180, h // 2 - 20),
        28,
        (100, 215, 90),
    )


def make_capture_window_topmost(win_name: str) -> bool:
    """Keep the capture window visible when enrollment is launched remotely."""

    ok = False
    try:
        topmost_prop = getattr(cv2, "WND_PROP_TOPMOST", None)
        if topmost_prop is not None:
            cv2.setWindowProperty(win_name, topmost_prop, 1)
            ok = True
    except Exception as exc:
        logger.debug("OpenCV 置顶窗口失败: win=%s error=%s", win_name, exc)

    if platform.system().lower() != "windows":
        if ok:
            logger.info("人脸注册窗口已请求置顶: backend=opencv win=%s", win_name)
        return ok

    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, win_name)
        if not hwnd:
            logger.debug("Win32 未找到人脸注册窗口句柄: win=%s", win_name)
            return ok

        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        user32.ShowWindow(hwnd, 5)
        user32.SetForegroundWindow(hwnd)
        logger.info("人脸注册窗口已置顶: backend=win32 win=%s hwnd=%s", win_name, hwnd)
        return True
    except Exception as exc:
        logger.warning("Win32 置顶人脸注册窗口失败: win=%s error=%s", win_name, exc)
        return ok


def _is_window_closed(win_name: str) -> bool:
    try:
        return cv2.getWindowProperty(win_name, cv2.WND_PROP_VISIBLE) < 1
    except Exception:
        return False


def prewarm_employee_voice(name: str) -> dict:
    url = f"{AVATAR_SERVER_URL}/employees/sync"
    payload = json.dumps({"name": name}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(_signed_headers("POST", url, payload))
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"语音生成接口失败 HTTP {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"无法连接数字人语音服务: {e}") from e

    if not data.get("ok"):
        raise RuntimeError(f"语音生成失败: {data}")
    return data


def _signed_headers(method: str, url: str, body: bytes) -> dict[str, str]:
    if not API_KEY or not API_SECRET:
        return {}
    timestamp = str(int(time.time()))
    path = urlparse(url).path
    signing_payload = f"{method.upper()}\n{path}\n{timestamp}\n".encode("utf-8") + body
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        signing_payload,
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-api-key": API_KEY,
        "x-timestamp": timestamp,
        "x-signature": signature,
    }


def enroll_employee_via_api(name: str, photos: list[tuple[np.ndarray, str, str]]) -> dict:
    embeddings = []
    for embedding, angle, path in photos:
        embeddings.append(
            {
                "embedding": np.asarray(embedding, dtype=np.float32).tolist(),
                "angle": angle,
                "photoPath": f"client_capture:{os.path.basename(path)}",
            }
        )
    try:
        data = SignedApiClient(base_url=API_BASE_URL, timeout=240).post(
            "/api/v1/employees/enroll-embeddings",
            {"name": name, "embeddings": embeddings},
            timeout=240,
        )
    except ApiClientError as exc:
        raise RuntimeError(f"员工向量录入 API 失败: {exc}") from exc
    if not data.get("ok"):
        raise RuntimeError(f"员工向量录入 API 失败: {data}")
    return data


def delete_captured_photos(save_dir: str) -> None:
    if os.path.isdir(save_dir):
        shutil.rmtree(save_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="人脸注册拍照工具")
    parser.add_argument("--name", default="", help="员工姓名；不传则进入命令行输入")
    return parser.parse_args()


def main(name: str = "", camera_index: int | None = None):
    name = (name or "").strip()
    if not name:
        name = input("请输入员工姓名: ").strip()
    try:
        name = normalize_employee_name(name)
    except ValueError as exc:
        print(f"姓名无效: {exc}")
        sys.exit(1)

    save_dir = str(tenant_employee_directory(EMPLOYEES_DIR, TENANT_ID, name))
    os.makedirs(save_dir, exist_ok=True)
    selected_camera_index = CAMERA_INDEX if camera_index is None else int(camera_index)

    camera_pause_owner = f"capture_faces:{os.getpid()}"
    cap = None
    try:
        pause_request = request_camera_pause(
            camera_pause_owner, reason=f"注册员工 {name}"
        )
        if wait_for_camera_released(pause_request):
            logger.info("识别引擎已释放摄像头，开始注册拍摄")
        else:
            logger.warning("等待识别引擎释放摄像头超时，将继续尝试打开摄像头")

        logger.info("人脸注册打开摄像头: index=%s name=%s", selected_camera_index, name)
        cap = cv2.VideoCapture(selected_camera_index)
        if not cap.isOpened():
            print("无法打开摄像头!")
            sys.exit(1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

        app = create_face_analysis()
        logger.info("模型就绪")
    except BaseException:
        if cap is not None:
            cap.release()
        clear_camera_pause(camera_pause_owner)
        raise

    photos: list[tuple[np.ndarray, str, str]] = []
    current_angle_idx = 0
    angle_count = 0
    angle_started_at = time.time()
    last_capture_at = 0.0
    frame_idx = 0
    cached_faces: list = []

    win_name = "人脸注册"
    cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
    window_topmost_done = make_capture_window_topmost(win_name)
    window_topmost_until = time.time() + WINDOW_TOPMOST_RETRY_SECONDS

    try:
        while True:
            if is_shutdown_requested():
                logger.info("人脸注册收到客户端退出请求，结束拍摄")
                break
            ret, raw_frame = cap.read()
            if not ret:
                break
            clean = raw_frame.copy()
            display_frame = cv2.flip(raw_frame, 1)
            frame_idx += 1

            if current_angle_idx >= len(ANGLES):
                draw_done(display_frame)
                cv2.imshow(win_name, display_frame)
                cv2.waitKey(1200)
                break

            angle_key, hint = ANGLES[current_angle_idx]
            now = time.time()
            next_capture_in = max(0.0, ANGLE_READY_SECONDS - (now - angle_started_at))
            draw_guide(
                display_frame,
                angle_key,
                hint,
                len(photos),
                TOTAL_PHOTOS,
                angle_count,
                next_capture_in,
            )

            if frame_idx % DETECT_EVERY_N == 0:
                cached_faces = app.get(raw_frame)
            for face in cached_faces:
                bbox = face.bbox.astype(int)
                display_w = display_frame.shape[1]
                display_bbox = (
                    display_w - int(bbox[2]),
                    int(bbox[1]),
                    display_w - int(bbox[0]),
                    int(bbox[3]),
                )
                cv2.rectangle(
                    display_frame,
                    (display_bbox[0], display_bbox[1]),
                    (display_bbox[2], display_bbox[3]),
                    (100, 215, 90),
                    2,
                    lineType=cv2.LINE_AA,
                )

            if (
                next_capture_in <= 0
                and cached_faces
                and now - last_capture_at >= AUTO_CAPTURE_INTERVAL_SECONDS
            ):
                face = max(cached_faces, key=lambda item: float(item.det_score))
                emb = face.normed_embedding
                ts = time.strftime("%Y%m%d_%H%M%S")
                filename = f"{angle_key}_{angle_count + 1}_{ts}.jpg"
                filepath = os.path.join(save_dir, filename)
                cv2.imwrite(filepath, clean)
                photos.append((emb, angle_key, filepath))
                angle_count += 1
                last_capture_at = now
                logger.info("自动拍照: %s #%d -> %s", angle_key, angle_count, filename)

                h, w = display_frame.shape[:2]
                flash = display_frame.copy()
                cv2.rectangle(flash, (0, 0), (w, h), (255, 255, 255), -1)
                cv2.addWeighted(flash, 0.18, display_frame, 0.82, 0, display_frame)

                if angle_count >= PHOTOS_PER_ANGLE:
                    current_angle_idx += 1
                    angle_count = 0
                    angle_started_at = time.time()
                    last_capture_at = 0.0
                    cached_faces = []

            cv2.imshow(win_name, display_frame)
            if not window_topmost_done and time.time() <= window_topmost_until:
                window_topmost_done = make_capture_window_topmost(win_name)
            if _is_window_closed(win_name):
                logger.info("人脸注册窗口已关闭，结束拍摄")
                break

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == ord("Q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        clear_camera_pause(camera_pause_owner)

    if len(photos) == 0:
        print("未拍摄任何照片, 退出")
        sys.exit(0)

    print(f"\n共拍摄 {len(photos)} 张照片, 正在录入员工底库...")
    if ENROLL_VIA_API:
        try:
            result = enroll_employee_via_api(name, photos)
            data = result.get("data") or {}
            print(
                "服务器录入成功: {name} ({embeddings} 条向量)".format(
                    name=name,
                    embeddings=data.get("embeddings", len(photos)),
                )
            )
        except Exception as e:
            print(f"服务器录入失败: {e}")
            print(f"照片已保存到: {save_dir}")
            print("为保护流程完整性，照片未删除。请修复后重试。")
            sys.exit(1)
    else:
        try:
            db = VectorDB()
            db.upsert_employee(name, photos, TENANT_ID)
            print(f"注册成功! {name} 已录入 pgvector ({len(photos)} 条向量)")
        except Exception as e:
            print(f"pgvector 写入失败: {e}")
            print(f"照片已保存到: {save_dir}")
            print("可以稍后手动运行注册")
            sys.exit(1)

        try:
            from core.attendance_db import AttendanceDB

            att_db = AttendanceDB()
            registered = att_db.register_employee(name, TENANT_ID)
            if registered:
                print(f"MySQL 同步成功: {name} 已录入 employees 表")
            else:
                print(f"MySQL: {name} 已存在, 跳过")
        except Exception as e:
            print(f"MySQL 同步失败: {e}")
            print(f"照片已保存到: {save_dir}")
            print("为保护流程完整性，照片未删除。请修复后重试。")
            sys.exit(1)

    if ENABLE_TTS_PREWARM:
        try:
            print("正在生成该员工姓名语音缓存...")
            result = prewarm_employee_voice(name)
            tts = result.get("results", [{}])[0].get("tts", {})
            print(
                "语音缓存生成完成: {generated}/{total} 新生成, {skipped} 已存在".format(
                    generated=tts.get("generated", 0),
                    total=tts.get("total", 0),
                    skipped=tts.get("skipped", 0),
                )
            )
        except Exception as e:
            print(f"语音缓存生成失败: {e}")
            print(f"照片已保存到: {save_dir}")
            print("为保护流程完整性，照片未删除。请修复后重试。")
            sys.exit(1)
    else:
        print("已跳过语音预生成，首次触发语音时会异步生成并缓存")

    try:
        delete_captured_photos(save_dir)
        print("已删除员工照片文件夹，仅保留向量和语音缓存")
    except Exception as e:
        print(f"照片删除失败，请手动删除 {EMPLOYEES_DIR}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    main(args.name)
