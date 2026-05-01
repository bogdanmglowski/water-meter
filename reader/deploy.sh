#!/usr/bin/env bash
set -euo pipefail

EXPECTED_SOURCE_HOSTNAME="smutas"
CURRENT_HOSTNAME="$(hostname -s)"

if [[ "$CURRENT_HOSTNAME" != "$EXPECTED_SOURCE_HOSTNAME" ]]; then
  echo "Błąd: ten skrypt wolno uruchamiać tylko na hoście źródłowym: $EXPECTED_SOURCE_HOSTNAME"
  echo "Aktualny host: $CURRENT_HOSTNAME"
  exit 1
fi

SRC_DIR="/home/bogdan/dev/workspaces/workspace_private_projects/water-meter-app/"
REMOTE_USER="bogdan"
REMOTE_HOST="192.168.10.134"
REMOTE_DIR="~/Downloads/water-meter"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Błąd: nie istnieje katalog źródłowy: $SRC_DIR"
  exit 1
fi

if [[ "$SRC_DIR" != */ ]]; then
  echo "Błąd: SRC_DIR musi kończyć się na /"
  exit 1
fi

echo "Źródło : $SRC_DIR"
echo "Cel    : ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"
echo

rsync -avz --delete --dry-run \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.idea/' \
  --exclude '.vscode/' \
  "$SRC_DIR" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo
read -r -p "Kontynuować właściwy deploy? [y/N] " answer

if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
  echo "Przerwano."
  exit 0
fi

rsync -avz --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.idea/' \
  --exclude '.vscode/' \
  "$SRC_DIR" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "${REMOTE_USER}@${REMOTE_HOST}" "
  set -e
  cd '${REMOTE_DIR}'
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"