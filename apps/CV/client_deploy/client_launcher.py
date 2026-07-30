"""Windows EXE launcher for the API-only frontdesk client."""

from __future__ import annotations

import os
import logging
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_avatar_browser_process: subprocess.Popen | None = None
_avatar_browser_lock = threading.Lock()


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _configure_logging(root: Path) -> None:
    log_path = root / "cache" / "logs" / "client.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    logging.getLogger(__name__).info("客户端日志已启用: %s", log_path)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_avatar_browser_url() -> str:
    explicit_url = os.environ.get("CLIENT_AVATAR_BROWSER_URL", "").strip()
    if explicit_url:
        url = explicit_url
    else:
        avatar_url = os.environ.get("AVATAR_SERVER_URL", "").strip()
        if avatar_url:
            url = _with_display_mode(avatar_url)
        else:
            url = _with_display_mode(
                os.environ.get("API_BASE_URL", "http://127.0.0.1").strip()
            )
    bootstrap_token = os.environ.get("CLIENT_AVATAR_BOOTSTRAP_TOKEN", "").strip()
    if bootstrap_token:
        url = _with_query_value(url, "bootstrap", bootstrap_token)
    return url


def _with_display_mode(url: str) -> str:
    if not _env_bool("CLIENT_AVATAR_DISPLAY_MODE", True):
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("display", "1")
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path or "/",
            urlencode(query),
            parts.fragment,
        )
    )


def _with_query_value(url: str, name: str, value: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[name] = value
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path or "/",
            urlencode(query),
            parts.fragment,
        )
    )


def _redact_browser_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "bootstrap" in query:
        query["bootstrap"] = "[REDACTED]"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _browser_security_origin(url: str) -> str:
    """Return only the origin accepted by Chromium's insecure-origin flag."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _browser_candidates() -> list[Path]:
    roots = [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relative_paths = [
        Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        Path("Google") / "Chrome" / "Application" / "chrome.exe",
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        for relative_path in relative_paths:
            candidates.append(Path(root) / relative_path)
    return candidates


def _default_browser_profile_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if base:
        return Path(base) / "CVClient" / "browser-profile"
    return Path.home() / "AppData" / "Local" / "CVClient" / "browser-profile"


def _open_avatar_browser(root: Path) -> subprocess.Popen | None:
    if not _env_bool("CLIENT_OPEN_AVATAR_BROWSER", True):
        return None

    url = _resolve_avatar_browser_url()
    os.environ.pop("CLIENT_AVATAR_BOOTSTRAP_TOKEN", None)
    if not url:
        return None

    args = []
    if _env_bool("CLIENT_BROWSER_AUTOPLAY", True):
        args.extend(["--autoplay-policy=no-user-gesture-required"])
    if _env_bool("CLIENT_BROWSER_TRUST_INSECURE_ORIGIN", True) and url.startswith(
        "http://"
    ):
        args.append(
            "--unsafely-treat-insecure-origin-as-secure="
            f"{_browser_security_origin(url)}"
        )

    user_data_dir = os.environ.get("CLIENT_BROWSER_USER_DATA_DIR", "").strip()
    if (
        not user_data_dir
        and _env_bool("CLIENT_BROWSER_TRUST_INSECURE_ORIGIN", True)
        and url.startswith("http://")
    ):
        user_data_dir = str(_default_browser_profile_dir())
    if user_data_dir:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={user_data_dir}")

    args.extend(["--no-first-run", "--disable-session-crashed-bubble"])
    if _env_bool("CLIENT_BROWSER_KIOSK_MODE", True):
        args.extend(["--kiosk", url])
    elif _env_bool("CLIENT_BROWSER_APP_MODE", True):
        args.append("--start-maximized")
        args.append(f"--app={url}")
    else:
        args.append("--start-maximized")
        args.append(url)

    log_path = root / "cache" / "logs" / "client-launcher.log"
    safe_url = _redact_browser_url(url)
    for browser_path in _browser_candidates():
        if not browser_path.exists():
            continue
        try:
            process = subprocess.Popen(
                [str(browser_path), *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log_path.write_text(
                f"opened avatar browser: {browser_path} {safe_url}\n",
                encoding="utf-8",
            )
            return process
        except Exception as exc:
            log_path.write_text(
                f"browser launch failed: {browser_path} {safe_url} {exc}\n",
                encoding="utf-8",
            )

    webbrowser.open(url, new=1, autoraise=True)
    log_path.write_text(
        f"opened avatar browser with default browser: {safe_url}\n",
        encoding="utf-8",
    )
    return None


def _prompt_activation_code() -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        code = simpledialog.askstring(
            "CVClient 设备激活",
            "首次启动，请粘贴云端管理员提供的一次性激活码：",
            parent=root,
        )
        root.destroy()
        return (code or "").strip()
    except Exception as exc:
        logging.getLogger(__name__).error("设备激活码输入窗口打开失败: %s", exc)
        return ""


def _show_startup_error(message: str) -> None:
    logging.getLogger(__name__).error("客户端启动失败: %s", message)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("CVClient 启动失败", message, parent=root)
        root.destroy()
    except Exception:
        pass


def _device_enrollment_requested() -> bool:
    mode = os.environ.get("CLIENT_DEVICE_ENROLLMENT", "auto").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return False
    if mode in {"1", "true", "yes", "on"}:
        return True
    from core.device_identity import DeviceIdentityStore

    has_identity = DeviceIdentityStore.default_path().exists()
    has_activation = bool(os.environ.get("CLIENT_ACTIVATION_CODE", "").strip())
    has_legacy_hmac = bool(
        os.environ.get("API_KEY", "").strip()
        and os.environ.get("API_SECRET", "").strip()
    )
    return has_identity or has_activation or not has_legacy_hmac


def _scrub_activation_code(env_path: Path) -> None:
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    changed = False
    output = []
    for line in lines:
        if line.strip().startswith("CLIENT_ACTIVATION_CODE="):
            output.append("CLIENT_ACTIVATION_CODE=")
            changed = changed or line.strip() != "CLIENT_ACTIVATION_CODE="
        else:
            output.append(line)
    if not changed:
        return
    temporary = env_path.with_name(f".{env_path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(temporary, env_path)


def _provision_device(root: Path) -> None:
    if not _device_enrollment_requested():
        logging.getLogger(__name__).info("设备自动注册未启用，继续使用旧 HMAC 凭据")
        return
    from core.device_identity import DeviceIdentityStore
    from core.device_provisioning import DeviceProvisioner

    identity_path = DeviceIdentityStore.default_path()
    os.environ["CLIENT_DEVICE_IDENTITY_PATH"] = str(identity_path)
    provisioner = DeviceProvisioner(
        os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        DeviceIdentityStore(identity_path),
    )
    outcome = provisioner.ensure_enrolled(
        os.environ.get("CLIENT_ACTIVATION_CODE", ""),
        activation_code_provider=_prompt_activation_code,
    )
    os.environ["TENANT_ID"] = outcome.identity.tenant_id
    os.environ["DEVICE_ID"] = outcome.identity.device_id
    os.environ["CLIENT_AVATAR_BOOTSTRAP_TOKEN"] = outcome.avatar_bootstrap_token
    if outcome.enrolled_now:
        _scrub_activation_code(root / ".env")
        os.environ.pop("CLIENT_ACTIVATION_CODE", None)
    logging.getLogger(__name__).info(
        "设备云端身份已就绪: tenant=%s device=%s identity=%s",
        outcome.identity.tenant_id,
        outcome.identity.device_id,
        identity_path,
    )


def _open_avatar_browser_and_watch(root: Path) -> None:
    global _avatar_browser_process
    process = _open_avatar_browser(root)
    if process is None:
        return
    with _avatar_browser_lock:
        _avatar_browser_process = process

    log_path = root / "cache" / "logs" / "client-launcher.log"

    def _watch_browser() -> None:
        global _avatar_browser_process
        exit_code = process.wait()
        with _avatar_browser_lock:
            if _avatar_browser_process is process:
                _avatar_browser_process = None
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"avatar browser exited: pid={process.pid} code={exit_code}\n")
        except Exception:
            pass
        try:
            from core.shutdown import request_shutdown

            request_shutdown("avatar_browser_closed")
        except Exception as exc:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"request shutdown after browser exit failed: {exc}\n")
            except Exception:
                pass

    threading.Thread(
        target=_watch_browser,
        name="AvatarBrowserWatcher",
        daemon=True,
    ).start()


def _terminate_avatar_browser(root: Path) -> None:
    with _avatar_browser_lock:
        process = _avatar_browser_process
    if process is None or process.poll() is not None:
        return

    log_path = root / "cache" / "logs" / "client-launcher.log"
    try:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"avatar browser terminated by client shutdown: pid={process.pid}\n"
            )
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"terminate avatar browser failed: pid={process.pid} error={exc}\n")


def main() -> int:
    root = _runtime_dir()
    os.chdir(root)
    (root / "cache" / "logs").mkdir(parents=True, exist_ok=True)
    _configure_logging(root)
    _load_env_file(root / ".env")
    _load_env_file(root / "_internal" / ".env")

    os.environ.setdefault("CLIENT_API_ONLY", "1")
    os.environ.setdefault("ENABLE_REALTIME_DIALOG", "0")
    os.environ.setdefault("VOICE_PIPELINE_ENABLED", "0")
    os.environ.setdefault("ENABLE_TTS_PREWARM", "0")
    bundled_models = root / "models" / "insightface"
    if not bundled_models.exists() and getattr(sys, "_MEIPASS", None):
        bundled_models = Path(sys._MEIPASS) / "models" / "insightface"
    if not bundled_models.exists():
        bundled_models = root / "_internal" / "models" / "insightface"
    if bundled_models.exists():
        os.environ["INSIGHTFACE_ROOT"] = str(bundled_models)

    try:
        _provision_device(root)
    except Exception as exc:
        _show_startup_error(str(exc))
        return 2

    threading.Timer(1.0, _open_avatar_browser_and_watch, args=(root,)).start()

    from app import main as app_main

    try:
        app_main()
    finally:
        _terminate_avatar_browser(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
