"""Signed multi-device recognition API load smoke test.

The default payload contains no faces, so it exercises authentication,
admission control, per-device session isolation and database/Redis summary
paths without creating attendance or stranger events.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PATH = "/api/v1/recognition/frame"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default="load-smoke")
    parser.add_argument("--devices", type=int, default=10)
    parser.add_argument("--requests-per-device", type=int, default=20)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--api-secret", default=os.getenv("API_SECRET", ""))
    return parser.parse_args()


def signature(secret: str, timestamp: str, body: bytes) -> str:
    prefix = f"POST\n{PATH}\n{timestamp}\n".encode()
    return hmac.new(secret.encode(), prefix + body, hashlib.sha256).hexdigest()


def run_device(args: argparse.Namespace, index: int) -> list[tuple[int, float]]:
    results: list[tuple[int, float]] = []
    interval = 1.0 / max(0.1, args.fps)
    next_send_at = time.perf_counter()
    for _ in range(max(1, args.requests_per_device)):
        delay = next_send_at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        next_send_at += interval
        body = json.dumps(
            {
                "tenant_id": args.tenant_id,
                "device_id": f"load-device-{index:03d}",
                "frame_width": 1280,
                "frame_height": 720,
                "faces": [],
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(time.time()))
        request = Request(
            args.base_url.rstrip("/") + PATH,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": args.api_key,
                "X-Timestamp": timestamp,
                "X-Signature": signature(args.api_secret, timestamp, body),
            },
        )
        started_at = time.perf_counter()
        try:
            with urlopen(request, timeout=10) as response:
                response.read()
                status = response.status
        except HTTPError as exc:
            exc.read()
            status = exc.code
        except (TimeoutError, URLError):
            status = 0
        results.append((status, (time.perf_counter() - started_at) * 1000))
    return results


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(value * len(ordered)) - 1))
    return ordered[index]


def main() -> int:
    args = parse_args()
    if not args.api_key or not args.api_secret:
        raise SystemExit("API_KEY and API_SECRET are required")
    started_at = time.perf_counter()
    all_results: list[tuple[int, float]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.devices)) as executor:
        futures = [executor.submit(run_device, args, index) for index in range(args.devices)]
        for future in as_completed(futures):
            all_results.extend(future.result())
    elapsed = time.perf_counter() - started_at
    latencies = [latency for _, latency in all_results]
    statuses: dict[int, int] = {}
    for status, _ in all_results:
        statuses[status] = statuses.get(status, 0) + 1
    summary = {
        "requests": len(all_results),
        "devices": args.devices,
        "elapsedSeconds": round(elapsed, 3),
        "throughputRps": round(len(all_results) / elapsed if elapsed else 0.0, 2),
        "latencyMs": {
            "mean": round(statistics.fmean(latencies) if latencies else 0.0, 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies, default=0.0), 3),
        },
        "statuses": statuses,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if statuses and set(statuses) == {200} else 1


if __name__ == "__main__":
    raise SystemExit(main())
