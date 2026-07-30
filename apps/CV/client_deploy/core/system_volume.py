"""Adjust local system output volume for frontdesk client tasks."""

from __future__ import annotations

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


POWERSHELL_VOLUME_SCRIPT = r"""
param(
    [string]$Direction = "set",
    [int]$Delta = 10,
    [double]$Level = -1
)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out uint pnChannelCount);
    int SetMasterVolumeLevel(float fLevelDB, Guid pguidEventContext);
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int GetMasterVolumeLevel(out float pfLevelDB);
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetChannelVolumeLevel(uint nChannel, float fLevelDB, Guid pguidEventContext);
    int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, Guid pguidEventContext);
    int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
    int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
    int GetMute(out bool pbMute);
    int GetVolumeStepInfo(out uint pnStep, out uint pnStepCount);
    int VolumeStepUp(Guid pguidEventContext);
    int VolumeStepDown(Guid pguidEventContext);
    int QueryHardwareSupport(out uint pdwHardwareSupportMask);
    int GetVolumeRange(out float pflVolumeMindB, out float pflVolumeMaxdB, out float pflVolumeIncrementdB);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
    int Activate(ref Guid id, int clsCtx, IntPtr activationParams, out IAudioEndpointVolume endpointVolume);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, IntPtr devices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
public class MMDeviceEnumeratorComObject { }

public class VolumeControl {
    static IAudioEndpointVolume GetEndpointVolume() {
        IMMDeviceEnumerator enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice device;
        Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 1, out device));
        Guid endpointVolumeId = typeof(IAudioEndpointVolume).GUID;
        IAudioEndpointVolume endpointVolume;
        Marshal.ThrowExceptionForHR(device.Activate(ref endpointVolumeId, 23, IntPtr.Zero, out endpointVolume));
        return endpointVolume;
    }

    public static string Adjust(string direction, int delta, double level) {
        IAudioEndpointVolume endpoint = GetEndpointVolume();
        float current;
        Marshal.ThrowExceptionForHR(endpoint.GetMasterVolumeLevelScalar(out current));
        float target = current;
        bool muted = false;

        if (direction == "increase") {
            target = Math.Min(1.0f, current + (float)(delta / 100.0));
            Marshal.ThrowExceptionForHR(endpoint.SetMute(false, Guid.Empty));
        } else if (direction == "decrease") {
            target = Math.Max(0.0f, current - (float)(delta / 100.0));
            Marshal.ThrowExceptionForHR(endpoint.SetMute(false, Guid.Empty));
        } else if (direction == "mute") {
            target = 0.0f;
            muted = true;
            Marshal.ThrowExceptionForHR(endpoint.SetMute(true, Guid.Empty));
        } else if (level >= 0) {
            target = Math.Min(1.0f, Math.Max(0.0f, (float)level));
            Marshal.ThrowExceptionForHR(endpoint.SetMute(false, Guid.Empty));
        }

        if (!muted) {
            Marshal.ThrowExceptionForHR(endpoint.SetMasterVolumeLevelScalar(target, Guid.Empty));
        }

        float finalLevel;
        bool finalMuted;
        Marshal.ThrowExceptionForHR(endpoint.GetMasterVolumeLevelScalar(out finalLevel));
        Marshal.ThrowExceptionForHR(endpoint.GetMute(out finalMuted));
        return String.Format("{0},{1}", Math.Round(finalLevel * 100), finalMuted.ToString().ToLower());
    }
}
"@

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output ([VolumeControl]::Adjust($Direction, $Delta, $Level))
"""


def adjust_system_volume(payload: dict) -> dict:
    if platform.system().lower() != "windows":
        raise RuntimeError(f"system volume adjustment is only implemented on Windows, got {platform.system()}")

    direction = str(payload.get("direction") or "set").strip().lower()
    if direction not in {"increase", "decrease", "mute", "set"}:
        direction = "set"
    delta = _clamp_int(payload.get("delta"), 10, 1, 50)
    level = _normalize_level(payload.get("level"))

    args = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"& {{\n{POWERSHELL_VOLUME_SCRIPT}\n}}",
        "-Direction",
        direction,
        "-Delta",
        str(delta),
        "-Level",
        str(level if level is not None else -1),
    ]
    logger.info(
        "执行系统音量调整: direction=%s delta=%s level=%s",
        direction,
        delta,
        level,
    )
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"PowerShell volume adjustment failed: {stderr[:500]}")

    output = (completed.stdout or "").strip().splitlines()[-1].strip()
    parts = [item.strip() for item in output.split(",", 1)]
    volume_percent = _clamp_int(parts[0] if parts else None, 0, 0, 100)
    muted = len(parts) > 1 and parts[1].lower() == "true"
    result = {
        "direction": direction,
        "delta": delta,
        "level": level,
        "volumePercent": volume_percent,
        "muted": muted,
    }
    logger.info("系统音量调整完成: %s", result)
    return result


def _clamp_int(value, fallback: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = fallback
    return max(low, min(high, number))


def _normalize_level(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))
