#!/bin/sh
set -eu

client_url="${CLIENT_URL:-http://localhost:5173}"
api_url="${API_URL:-http://localhost:5173/api/health}"

printf '\n%s\n' '========================================'
printf 'Water Meter client: %s\n' "$client_url"
printf 'Water Meter API:    %s\n' "$api_url"
printf '%s\n\n' '========================================'
