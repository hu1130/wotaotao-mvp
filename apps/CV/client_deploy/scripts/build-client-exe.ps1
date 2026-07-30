param(
    [string]$ServerBaseUrl = "http://127.0.0.1",
    [string]$OutputRoot = "",
    [string]$PythonExe = "",
    [string]$IconPath = "",
    [switch]$Windowed,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$ClientRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $ClientRoot
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent $ClientRoot)
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $WorkspaceRoot "dist_client_exe"
}

$ServerBaseUrl = $ServerBaseUrl.TrimEnd("/")
$BuildRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$EnvPath = Join-Path $BuildRoot ".env"
$ModelRoot = Join-Path $BuildRoot "insightface"
$SpecPath = Join-Path $BuildRoot "CVClient.spec"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "build"
$StageRoot = Join-Path $BuildRoot "source"
$GeneratedIconPath = Join-Path $BuildRoot "CVClient.ico"
$MaterializeScript = Join-Path $RepoRoot "scripts\materialize-runtime.ps1"
$LocalPython = Join-Path $ClientRoot ".venv\Scripts\python.exe"
$SharedPython = "D:\CV\.venv\Scripts\python.exe"

if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    $Python = [System.IO.Path]::GetFullPath($PythonExe)
} elseif (Test-Path -LiteralPath $SharedPython) {
    $Python = $SharedPython
} else {
    $Python = $LocalPython
}

function Write-Info($Message) {
    Write-Host "[build-client-exe] $Message" -ForegroundColor Cyan
}

function Quote-Py($Value) {
    return ($Value -replace "\\", "\\") -replace "'", "\'"
}

function Resolve-ClientIcon($IconPathValue) {
    if ([string]::IsNullOrWhiteSpace($IconPathValue)) {
        return ""
    }
    $ResolvedIcon = [System.IO.Path]::GetFullPath($IconPathValue)
    if (-not (Test-Path -LiteralPath $ResolvedIcon)) {
        throw "Icon file not found: $ResolvedIcon"
    }
    $Extension = [System.IO.Path]::GetExtension($ResolvedIcon).ToLowerInvariant()
    if ($Extension -eq ".ico") {
        return $ResolvedIcon
    }
    if ($Extension -notin @(".png", ".jpg", ".jpeg")) {
        throw "Unsupported icon file type: $Extension. Use .ico, .png, .jpg, or .jpeg."
    }
    Write-Info "Converting icon image to .ico: $ResolvedIcon -> $GeneratedIconPath"
    & $Python -c "from PIL import Image; import sys; img=Image.open(sys.argv[1]).convert('RGBA'); img.save(sys.argv[2], sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])" $ResolvedIcon $GeneratedIconPath
    if ($LASTEXITCODE -ne 0) {
        throw "Icon conversion failed: $ResolvedIcon"
    }
    return $GeneratedIconPath
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

if (-not (Test-Path -LiteralPath $Python) -and $Python -eq $LocalPython) {
    Write-Info "Creating virtual environment: $Python"
    python -m venv (Join-Path $ClientRoot ".venv")
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

Write-Info "Using Python: $Python"

if (-not $SkipInstall -and $Python -eq $LocalPython) {
    Write-Info "Installing client requirements with Tsinghua mirror"
    & $Python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    & $Python -m pip install -r (Join-Path $ClientRoot "requirements.client.txt") -i https://pypi.tuna.tsinghua.edu.cn/simple
    & $Python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
} elseif (-not $SkipInstall) {
    Write-Info "Shared Python detected; skipping full dependency install"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python -c "import PyInstaller, cryptography" *> $null
    $BuildDependenciesReady = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $PreviousErrorActionPreference
    if (-not $BuildDependenciesReady) {
        Write-Info "Installing client build-time dependencies into shared environment"
        & $Python -m pip install pyinstaller "cryptography>=43.0.0" -i https://pypi.tuna.tsinghua.edu.cn/simple
    }
}

if (-not (Test-Path -LiteralPath $ModelRoot)) {
    throw "Missing InsightFace model directory: $ModelRoot. Expected buffalo_l models under dist_client_exe\insightface."
}

if (-not (Test-Path -LiteralPath $MaterializeScript)) {
    throw "Missing shared runtime materializer: $MaterializeScript"
}
Write-Info "Materializing shared + client runtime: $StageRoot"
& $MaterializeScript -Role client -Destination $StageRoot -Force

$envContent = @"
DEPLOY_ROLE=collector
DEVICE_ID=
TENANT_ID=
SITE_ID=default

API_KEY=
API_SECRET=
API_BASE_URL=$ServerBaseUrl
AVATAR_SERVER_URL=$ServerBaseUrl
CLIENT_API_ONLY=1
CLIENT_DEVICE_ENROLLMENT=auto
CLIENT_ACTIVATION_CODE=
CLIENT_DEVICE_IDENTITY_PATH=
CLIENT_APP_VERSION=1.1.0
CLIENT_OPEN_AVATAR_BROWSER=1
CLIENT_AVATAR_BROWSER_URL=
CLIENT_AVATAR_DISPLAY_MODE=1
CLIENT_BROWSER_KIOSK_MODE=1
CLIENT_BROWSER_APP_MODE=1
CLIENT_BROWSER_AUTOPLAY=1
CLIENT_BROWSER_TRUST_INSECURE_ORIGIN=1
CLIENT_BROWSER_USER_DATA_DIR=
CLIENT_TASKS_ENABLED=1
CLIENT_TASK_POLL_SECONDS=2

CAMERA_INDEX=0
FRAME_WIDTH=1280
FRAME_HEIGHT=720
CAMERA_BUFFER_SIZE=1
ENABLE_GUI=0
USE_GPU=0

INSIGHTFACE_MODEL=buffalo_l
INSIGHTFACE_ALLOWED_MODULES=detection,recognition,genderage
INSIGHTFACE_DET_SIZE=640x640
DETECTION_THRESHOLD=0.5
TRACKER_BACKEND=opencv
DETECT_INTERVAL=15
MAX_PROCESS_FACES=3

GESTURE_ENABLED=0
ENABLE_REALTIME_DIALOG=0
REALTIME_DIALOG_APP_KEY=
VOICE_PIPELINE_ENABLED=0
ENABLE_TTS_PREWARM=0
"@
$envContent | Set-Content -LiteralPath $EnvPath -Encoding UTF8

$consoleValue = if ($Windowed) { "False" } else { "True" }
$clientLauncher = Quote-Py (Join-Path $StageRoot "client_launcher.py")
$clientRootPy = Quote-Py $StageRoot
$envPathPy = Quote-Py $EnvPath
$modelRootPy = Quote-Py $ModelRoot
$gestureModelPy = Quote-Py (Join-Path $StageRoot "core\gesture\model\gesture_classifier.joblib")
$ResolvedIcon = Resolve-ClientIcon $IconPath
$iconLine = ""
if (-not [string]::IsNullOrWhiteSpace($ResolvedIcon)) {
    $iconPathPy = Quote-Py $ResolvedIcon
    $iconLine = "    icon='$iconPathPy',"
}

$specContent = @"
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('$envPathPy', '.'),
    ('$modelRootPy', 'models/insightface'),
    ('$gestureModelPy', 'core/gesture/model'),
]
binaries = []
hiddenimports = ['sklearn.neighbors._partition_nodes', 'tools.capture_faces', 'core.system_volume']

for package_name in ['cv2', 'insightface', 'onnxruntime', 'pygame', 'mediapipe', 'sklearn', 'cryptography']:
    try:
        tmp_ret = collect_all(package_name)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception as exc:
        print(f'collect_all skipped for {package_name}: {exc}')

a = Analysis(
    ['$clientLauncher'],
    pathex=['$clientRootPy'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CVClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=$consoleValue,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
$iconLine
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CVClient',
)
"@
$specContent | Set-Content -LiteralPath $SpecPath -Encoding UTF8

Write-Info "Building CVClient.exe"
& $Python -m PyInstaller $SpecPath --distpath $DistRoot --workpath $WorkRoot --noconfirm --clean

$ClientDist = Join-Path $DistRoot "CVClient"
Copy-Item -LiteralPath $EnvPath -Destination (Join-Path $ClientDist ".env") -Force

$stopScript = @"
@echo off
taskkill /IM CVClient.exe /F
"@
$stopScript | Set-Content -LiteralPath (Join-Path $ClientDist "StopCVClient.bat") -Encoding ASCII

$exitVbs = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "StopCVClient.bat", 0, True
"@
$exitVbs | Set-Content -LiteralPath (Join-Path $ClientDist "退出客户端.vbs") -Encoding Unicode

Write-Info "Done: $(Join-Path $ClientDist 'CVClient.exe')"
