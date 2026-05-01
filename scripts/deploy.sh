#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/.env.production"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh [up|down|restart|logs|ps|config|pull] [--demo]

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
EOF
}

command="up"
demo_seed="false"

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
  SEED_DEMO_DATA="$demo_seed" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

case "$command" in
  up)
    compose up -d --build
    ;;
  down)
    compose down
    ;;
  restart)
    compose up -d --build --force-recreate
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
