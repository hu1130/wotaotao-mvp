$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

if (-not (Test-Path -LiteralPath ".env")) {
    if (Test-Path -LiteralPath ".env.client.example") {
        Copy-Item ".env.client.example" ".env"
        Write-Host "Created .env from .env.client.example. Edit server addresses and secrets, then run again." -ForegroundColor Yellow
        exit 1
    }
    throw "Missing .env and .env.client.example"
}

if (-not (Test-Path -LiteralPath ".venv")) {
    python -m venv .venv
}

$Python = Join-Path $RootDir ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
& $Python -m pip install -r requirements.client.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
& $Python app.py
