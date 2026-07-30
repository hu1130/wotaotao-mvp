"""User-mode TCP proxy from Windows localhost to a WSL localhost service."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading

READY_MARKER = b"__CV_WSL_TCP_PROXY_READY__\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward a Windows TCP port to WSL.")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--remote-host", default="127.0.0.1")
    parser.add_argument("--remote-port", type=int, required=True)
    parser.add_argument(
        "--remote-unix-socket",
        default="",
        help="Connect to this Unix socket inside WSL instead of remote host/port.",
    )
    parser.add_argument(
        "--strip-leading-bytes-until",
        default="",
        help=(
            "Drop initial bytes from WSL stdout until one of these byte values is seen. "
            "Useful when WSL emits startup warnings before a binary protocol response."
        ),
    )
    args = parser.parse_args()
    strip_until = args.strip_leading_bytes_until.encode("ascii", errors="ignore")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(64)
    print(
        f"Forwarding {args.listen_host}:{args.listen_port} "
        f"-> WSL {args.remote_unix_socket or (str(args.remote_host) + ':' + str(args.remote_port))}",
        flush=True,
    )

    while True:
        client, address = server.accept()
        thread = threading.Thread(
            target=_handle_client,
            args=(
                client,
                address,
                args.remote_host,
                args.remote_port,
                args.remote_unix_socket,
                strip_until,
            ),
            daemon=True,
        )
        thread.start()


def _handle_client(
    client: socket.socket,
    address: tuple[str, int],
    remote_host: str,
    remote_port: int,
    remote_unix_socket: str,
    strip_until: bytes,
) -> None:
    command = [
        "wsl.exe",
        "-e",
        "python3",
        "-u",
        "-c",
        _remote_python_code(remote_host, remote_port, remote_unix_socket),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    try:
        if not _wait_for_ready_marker(process.stdout):
            return
        upstream = threading.Thread(
            target=_copy_socket_to_pipe,
            args=(client, process.stdin),
            daemon=True,
        )
        downstream = threading.Thread(
            target=_copy_pipe_to_socket,
            args=(process.stdout, client, strip_until),
            daemon=True,
        )
        upstream.start()
        downstream.start()
        upstream.join()
        downstream.join()
    finally:
        try:
            client.close()
        except OSError:
            pass
        if process.poll() is None:
            process.kill()


def _copy_socket_to_pipe(source: socket.socket, target) -> None:
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            os.write(target.fileno(), chunk)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            target.close()
        except OSError:
            pass


def _copy_pipe_to_socket(source, target: socket.socket, strip_until: bytes) -> None:
    first_chunk = True
    try:
        while True:
            chunk = os.read(source.fileno(), 65536)
            if not chunk:
                break
            if first_chunk and strip_until:
                first_chunk = False
                start = _find_first_protocol_byte(chunk, strip_until)
                if start < 0:
                    continue
                chunk = chunk[start:]
            elif first_chunk:
                first_chunk = False
            target.sendall(chunk)
    except OSError:
        pass


def _wait_for_ready_marker(source) -> bool:
    buffer = bytearray()
    while True:
        chunk = os.read(source.fileno(), 1)
        if not chunk:
            return False
        buffer.extend(chunk)
        marker_at = buffer.find(READY_MARKER)
        if marker_at >= 0:
            return True
        if len(buffer) > 65536:
            del buffer[: len(buffer) - len(READY_MARKER)]


def _find_first_protocol_byte(chunk: bytes, allowed: bytes) -> int:
    positions = [chunk.find(bytes([byte])) for byte in allowed]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else -1


def _remote_python_code(
    remote_host: str,
    remote_port: int,
    remote_unix_socket: str = "",
) -> str:
    if remote_unix_socket:
        connect_code = f"""
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect({remote_unix_socket!r})
""".strip()
    else:
        connect_code = f"s = socket.create_connection(({remote_host!r}, {remote_port}), 10)"
    return f"""
import socket
import sys
import threading
import os

{connect_code}
sys.stdout.buffer.write({READY_MARKER!r})
sys.stdout.buffer.flush()

def up():
    try:
        while True:
            b = os.read(0, 65536)
            if not b:
                break
            s.sendall(b)
    except Exception:
        pass
    try:
        s.shutdown(socket.SHUT_WR)
    except Exception:
        pass

threading.Thread(target=up, daemon=True).start()
out = sys.stdout.buffer
while True:
    b = s.recv(65536)
    if not b:
        break
    out.write(b)
    out.flush()
""".strip()


if __name__ == "__main__":
    raise SystemExit(main())
