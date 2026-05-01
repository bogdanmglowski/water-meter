#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

docker compose -f "${ROOT_DIR}/infra/docker-compose.yml" exec -T db \
  psql -U "${POSTGRES_USER:-meter}" -d "${POSTGRES_DB:-water_meter}" \
  < "${ROOT_DIR}/infra/db/seed.sql"

printf 'Seeded PostgreSQL with two years of 10-minute water meter readings.\n'
