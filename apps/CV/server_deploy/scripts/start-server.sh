#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f ".env.server" ]; then
  echo "Missing .env.server. Copy .env.server.example to .env.server and edit secrets first."
  exit 1
fi

mkdir -p cache avatar/cache employees knowledge_base

docker compose --env-file .env.server -f docker-compose.deploy.yml up -d --build
docker compose --env-file .env.server -f docker-compose.deploy.yml ps
