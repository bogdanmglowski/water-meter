#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo cp ${ROOT_DIR}/infra/systemd/water-meter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-meter.service
