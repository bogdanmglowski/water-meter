#!/bin/sh
set -eu

db_host="${POSTGRES_HOST:-db}"
db_port="${POSTGRES_PORT:-5432}"
db_user="${POSTGRES_USER:-water-meter}"
db_name="${POSTGRES_DB:-water-meter}"

export PGPASSWORD="${POSTGRES_PASSWORD:-water-meter}"
seed_demo_data="${SEED_DEMO_DATA:-true}"

case "$seed_demo_data" in
  1|true|TRUE|yes|YES|on|ON)
    ;;
  0|false|FALSE|no|NO|off|OFF)
    printf 'Skipping seed because SEED_DEMO_DATA=%s.\n' "$seed_demo_data"
    exit 0
    ;;
  *)
    printf 'Invalid SEED_DEMO_DATA value: %s\n' "$seed_demo_data" >&2
    exit 1
    ;;
esac

psql_args="host=${db_host} port=${db_port} user=${db_user} dbname=${db_name}"

table_exists="$(psql "$psql_args" -tAc "SELECT to_regclass('public.meter_readings') IS NOT NULL")"

if [ "$table_exists" = "t" ]; then
  row_count="$(psql "$psql_args" -tAc "SELECT COUNT(*) FROM meter_readings")"
else
  row_count="0"
fi

if [ "$row_count" != "0" ]; then
  printf 'Skipping seed, meter_readings already has %s rows.\n' "$row_count"
  exit 0
fi

printf 'Seeding demo water meter readings...\n'
psql "$psql_args" -f /seed/seed.sql
printf 'Seed complete.\n'
