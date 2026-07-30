"""Audio inspection and deterministic prompt preparation for clone training."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioInspection:
    path: str
    duration_seconds: float
    codec: str
    sample_rate: int
    channels: int
    bit_rate: int
    integrated_lufs: float | None
    true_peak_dbfs: float | None
    silence_ratio: float
    clipping_ratio: float
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedCandidate:
    path: str
    start_seconds: float
    duration_seconds: float
    inspection: AudioInspection


class MediaToolchain:
    def __init__(self) -> None:
        self.wsl = False
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if self.ffmpeg and self.ffprobe:
            return
        if os.name == "nt" and shutil.which("wsl.exe"):
            self.wsl = True
            self.ffmpeg = "ffmpeg"
            self.ffprobe = "ffprobe"
            return
        raise RuntimeError("ffmpeg and ffprobe are required")

    def path(self, value: str | Path) -> str:
        path = Path(value).expanduser().resolve()
        if not self.wsl:
            return str(path)
        drive = path.drive.rstrip(":").lower()
        tail = path.as_posix().split(":", 1)[-1].lstrip("/")
        return f"/mnt/{drive}/{tail}"

    def run(self, tool: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        binary = self.ffprobe if tool == "ffprobe" else self.ffmpeg
        command = (["wsl.exe", binary] if self.wsl else [binary]) + args
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def inspect_audio(path: str | Path, tools: MediaToolchain | None = None) -> AudioInspection:
    tools = tools or MediaToolchain()
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    probe = tools.run(
        "ffprobe",
        [
            "-v",
            "error",
            "-show_entries",
            "format=duration,bit_rate:stream=codec_name,codec_type,sample_rate,channels",
            "-of",
            "json",
            tools.path(source),
        ],
    )
    metadata = json.loads(probe.stdout)
    stream = next(
        (item for item in metadata.get("streams", []) if item.get("codec_type") == "audio"),
        {},
    )
    duration = float(metadata.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("audio duration is missing or invalid")

    loudness = tools.run(
        "ffmpeg",
        [
            "-hide_banner",
            "-nostats",
            "-i",
            tools.path(source),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    combined = loudness.stdout + "\n" + loudness.stderr
    lufs = _last_float(combined, r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
    peak = _last_float(combined, r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS")

    with tempfile.TemporaryDirectory(prefix="voice-inspect-") as temp_dir:
        pcm_path = Path(temp_dir) / "inspect.wav"
        tools.run(
            "ffmpeg",
            [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                tools.path(source),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                tools.path(pcm_path),
            ],
        )
        silence_ratio, clipping_ratio = _pcm_quality(pcm_path)

    return AudioInspection(
        path=str(source),
        duration_seconds=round(duration, 3),
        codec=str(stream.get("codec_name") or ""),
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
        bit_rate=int(metadata.get("format", {}).get("bit_rate") or 0),
        integrated_lufs=lufs,
        true_peak_dbfs=peak,
        silence_ratio=round(silence_ratio, 6),
        clipping_ratio=round(clipping_ratio, 8),
        sha256=_sha256(source),
    )


def prepare_candidates(
    source: str | Path,
    output_dir: str | Path,
    *,
    segment_seconds: float = 14.0,
    count: int = 3,
    tools: MediaToolchain | None = None,
) -> list[PreparedCandidate]:
    tools = tools or MediaToolchain()
    inspection = inspect_audio(source, tools)
    segment_seconds = min(30.0, max(10.0, float(segment_seconds)))
    if inspection.duration_seconds < segment_seconds:
        raise ValueError("source audio is shorter than the requested clone prompt")
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    available = max(0.0, inspection.duration_seconds - segment_seconds)
    fractions = ([0.12, 0.45, 0.78] if count == 3 else [i / max(1, count - 1) for i in range(count)])
    candidates: list[PreparedCandidate] = []
    for index, fraction in enumerate(fractions[: max(1, min(5, count))], start=1):
        start = round(available * fraction, 3)
        destination = output / f"candidate-{index:02d}.wav"
        tools.run(
            "ffmpeg",
            [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(start),
                "-i",
                tools.path(source),
                "-t",
                str(segment_seconds),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                tools.path(destination),
            ],
        )
        candidate_inspection = inspect_audio(destination, tools)
        candidates.append(
            PreparedCandidate(
                path=str(destination),
                start_seconds=start,
                duration_seconds=candidate_inspection.duration_seconds,
                inspection=candidate_inspection,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            item.inspection.clipping_ratio,
            item.inspection.silence_ratio,
            abs((item.inspection.integrated_lufs or -18.0) + 18.0),
        ),
    )


def convert_to_pcm16k(
    source: str | Path,
    destination: str | Path,
    tools: MediaToolchain | None = None,
) -> Path:
    """Create the exact mono PCM format expected by streaming ASR."""

    tools = tools or MediaToolchain()
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tools.run(
        "ffmpeg",
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            tools.path(source_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "-c:a",
            "pcm_s16le",
            tools.path(destination_path),
        ],
    )
    return destination_path


def inspection_payload(value: AudioInspection | PreparedCandidate) -> dict:
    return asdict(value)


def _pcm_quality(path: Path) -> tuple[float, float]:
    with wave.open(str(path), "rb") as reader:
        sample_rate = reader.getframerate()
        samples = array("h")
        samples.frombytes(reader.readframes(reader.getnframes()))
    if not samples:
        return 1.0, 0.0
    clipping = sum(1 for value in samples if abs(value) >= 32700) / len(samples)
    frame_size = max(1, int(sample_rate * 0.02))
    silent = 0
    frames = 0
    threshold = 32768.0 * math.pow(10.0, -48.0 / 20.0)
    for offset in range(0, len(samples), frame_size):
        frame = samples[offset : offset + frame_size]
        if not frame:
            continue
        rms = math.sqrt(sum(float(value) * float(value) for value in frame) / len(frame))
        silent += int(rms < threshold)
        frames += 1
    return silent / max(1, frames), clipping


def _last_float(text: str, pattern: str) -> float | None:
    matches = re.findall(pattern, text)
    return float(matches[-1]) if matches else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
