#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f ".env" ]; then
  if [ -f ".env.client.example" ]; then
    cp .env.client.example .env
    echo "Created .env from .env.client.example. Edit server addresses and secrets, then run again."
    exit 1
  fi
  echo "Missing .env and .env.client.example."
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -r requirements.client.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python app.py
