#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "$#" -eq 0 ]; then
  docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f api avatar
else
  docker compose --env-file .env.server -f docker-compose.deploy.yml logs -f "$@"
fi
