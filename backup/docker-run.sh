#!/bin/sh
set -eu

require_non_empty() {
    name="$1"
    value="$2"
    if [ -z "$value" ]; then
        echo "Missing required environment variable: $name" >&2
        exit 1
    fi
}

pg_host="${PGHOST:-}"
pg_port="${PGPORT:-5432}"
pg_database="${PGDATABASE:-}"
pg_user="${PGUSER:-}"
pg_password="${PGPASSWORD:-}"
backup_target_dir="${BACKUP_TARGET_DIR:-/backups}"
backup_host_dir="${BACKUP_HOST_DIR:-}"
backup_file_prefix="${BACKUP_FILE_PREFIX:-water-meter}"
backup_wait_seconds="${BACKUP_WAIT_SECONDS:-30}"
timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"

require_non_empty "PGHOST" "$pg_host"
require_non_empty "PGDATABASE" "$pg_database"
require_non_empty "PGUSER" "$pg_user"
require_non_empty "PGPASSWORD" "$pg_password"
require_non_empty "BACKUP_TARGET_DIR" "$backup_target_dir"
require_non_empty "BACKUP_WAIT_SECONDS" "$backup_wait_seconds"

mkdir -p "$backup_target_dir"
backup_path="${backup_target_dir%/}/${backup_file_prefix}-${pg_database}-${timestamp}.dump"

export PGPASSWORD="$pg_password"

echo "Waiting for PostgreSQL at ${pg_host}:${pg_port}"
attempt=0
while ! pg_isready --host "$pg_host" --port "$pg_port" --username "$pg_user" --dbname "$pg_database" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$backup_wait_seconds" ]; then
        echo "PostgreSQL did not become ready within ${backup_wait_seconds}s" >&2
        exit 1
    fi
    sleep 1
done

echo "Creating PostgreSQL backup for ${pg_database}"
pg_dump \
    --format=custom \
    --no-owner \
    --no-privileges \
    --host "$pg_host" \
    --port "$pg_port" \
    --username "$pg_user" \
    --dbname "$pg_database" \
    --file "$backup_path"

echo "Backup written to ${backup_path}"
if [ -n "$backup_host_dir" ]; then
    echo "Host destination: ${backup_host_dir}"
fi
