#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "$ROOT_DIR"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/.env"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh [up|start|down|restart|logs|ps|config|pull|backup] [--demo] [--reader]

Commands:
  up       Build and start the deployment stack in the background
  start    Start the deployment stack without rebuilding images
  down     Stop the deployment stack
  restart  Recreate the deployment stack
  logs     Follow compose logs
  ps       Show compose service status
  config   Render the resolved compose configuration
  pull     Pull newer base images before the next restart
  backup   Run a one-off PostgreSQL backup into BACKUP_HOST_DIR

Flags:
  --demo   Enable demo seeding for an empty database
  --reader Enable the Reader service profile
EOF
}

command="up"
demo_seed="false"
reader_enabled="false"
backup_enabled="false"

if [[ $# -gt 0 ]]; then
  case "$1" in
    up|start|down|restart|logs|ps|config|pull|backup)
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
  printf 'Missing %s. Create it from .env.example first.\n' "$ENV_FILE" >&2
  exit 1
fi

strip_matching_quotes() {
  local value="$1"

  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value#\'}"
    value="${value%\'}"
  fi

  printf '%s\n' "$value"
}

read_env_file_value() {
  local key="$1"
  local line

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"

    if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
      continue
    fi

    if [[ "$line" == "$key="* ]]; then
      strip_matching_quotes "${line#*=}"
      return 0
    fi
  done < "$ENV_FILE"

  return 1
}

resolve_backup_host_dir() {
  if [[ -n "${BACKUP_HOST_DIR:-}" ]]; then
    strip_matching_quotes "$BACKUP_HOST_DIR"
    return 0
  fi

  read_env_file_value "BACKUP_HOST_DIR"
}

validate_backup_host_dir() {
  local backup_host_dir

  if ! backup_host_dir="$(resolve_backup_host_dir)"; then
    printf 'Missing BACKUP_HOST_DIR in %s.\n' "$ENV_FILE" >&2
    exit 1
  fi

  if [[ "$backup_host_dir" != /* ]]; then
    printf 'BACKUP_HOST_DIR must be an absolute path, got: %s\n' "$backup_host_dir" >&2
    exit 1
  fi

  mkdir -p "$backup_host_dir"

  if [[ ! -d "$backup_host_dir" ]]; then
    printf 'BACKUP_HOST_DIR is not a directory: %s\n' "$backup_host_dir" >&2
    exit 1
  fi

  if [[ ! -w "$backup_host_dir" ]]; then
    printf 'BACKUP_HOST_DIR is not writable: %s\n' "$backup_host_dir" >&2
    exit 1
  fi
}

compose() {
  local -a compose_profiles=()
  local compose_profiles_value=""

  if [[ "$reader_enabled" == "true" ]]; then
    compose_profiles+=("reader")
  fi

  if [[ "$backup_enabled" == "true" ]]; then
    compose_profiles+=("backup")
  fi

  if ((${#compose_profiles[@]} > 0)); then
    local IFS=,
    compose_profiles_value="${compose_profiles[*]}"
  fi

  SEED_DEMO_DATA="$demo_seed" COMPOSE_PROFILES="$compose_profiles_value" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

db_is_running() {
  local service

  while IFS= read -r service; do
    if [[ "$service" == "db" ]]; then
      return 0
    fi
  done < <(compose ps --status running --services 2>/dev/null || true)

  return 1
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

compose_start() {
  compose up -d --no-build
}

compose_backup() {
  local started_db_for_backup="false"
  local status=0

  backup_enabled="true"
  validate_backup_host_dir

  if ! db_is_running; then
    compose up -d db
    started_db_for_backup="true"
  fi

  if compose run --rm --build --no-deps -u "$(id -u):$(id -g)" backup; then
    :
  else
    status=$?
  fi

  if [[ "$started_db_for_backup" == "true" ]]; then
    compose stop db >/dev/null || true
  fi

  if [[ "$status" -ne 0 ]]; then
    exit "$status"
  fi
}

case "$command" in
  up)
    compose_up
    ;;
  start)
    compose_start
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
  backup)
    compose_backup
    ;;
esac
