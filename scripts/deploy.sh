#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/.env.production"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh [up|down|restart|logs|ps|config|pull] [--demo] [--reader]

Commands:
  up       Build and start the deployment stack in the background
  down     Stop the deployment stack
  restart  Recreate the deployment stack
  logs     Follow compose logs
  ps       Show compose service status
  config   Render the resolved compose configuration
  pull     Pull newer base images before the next restart

Flags:
  --demo   Enable demo seeding for an empty database
  --reader Enable the Reader service profile
EOF
}

command="up"
demo_seed="false"
reader_enabled="false"

if [[ $# -gt 0 ]]; then
  case "$1" in
    up|down|restart|logs|ps|config|pull)
      command="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
  esac
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo)
      demo_seed="true"
      ;;
    --reader)
      reader_enabled="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Missing %s. Create it from .env.production.example first.\n' "$ENV_FILE" >&2
  exit 1
fi

compose() {
  compose_profiles=""
  if [[ "$reader_enabled" == "true" ]]; then
    compose_profiles="reader"
  fi
  SEED_DEMO_DATA="$demo_seed" COMPOSE_PROFILES="$compose_profiles" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

print_failure_diagnostics() {
  printf '\nDeployment failed. Current service status:\n' >&2
  compose ps >&2 || true

  printf '\nRecent backend logs:\n' >&2
  backend_logs="$(compose logs --tail=120 backend 2>&1 || true)"
  printf '%s\n' "$backend_logs" >&2

  if grep -Fq "password authentication failed" <<<"$backend_logs"; then
    printf '\nPostgres authentication failed for the backend.\n' >&2
    printf 'If you changed POSTGRES_USER or POSTGRES_PASSWORD after the DB volume was created,\n' >&2
    printf 'the persisted database still expects the old credentials.\n' >&2
    printf 'If keeping the current DB data matters, restore the original credentials in %s.\n' "$ENV_FILE" >&2
    printf 'If data loss is acceptable, recreate the DB volume with:\n' >&2
    printf '  docker compose --env-file %s -f %s down -v\n' "$ENV_FILE" "$COMPOSE_FILE" >&2
    printf 'Then start the stack again with:\n' >&2
    printf '  ./scripts/deploy.sh up\n' >&2
  fi
}

compose_up() {
  local -a args=("up" "-d" "--build")

  if [[ "${1:-false}" == "true" ]]; then
    args+=("--force-recreate")
  fi

  if ! compose "${args[@]}"; then
    print_failure_diagnostics
    exit 1
  fi
}

case "$command" in
  up)
    compose_up
    ;;
  down)
    compose down
    ;;
  restart)
    compose_up true
    ;;
  logs)
    compose logs -f
    ;;
  ps)
    compose ps
    ;;
  config)
    compose config
    ;;
  pull)
    compose pull
    ;;
esac
