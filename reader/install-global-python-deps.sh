#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed." >&2
  exit 1
fi

SUDO=""
if [[ "${EUID}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "This script needs root privileges for a global install. Run it as root or install sudo." >&2
    exit 1
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update
  $SUDO apt-get install -y \
    python3-pip \
    python3-venv \
    python3-opencv \
    python3-numpy \
    python3-pytest \
    tesseract-ocr \
    libgl1
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "python3 -m pip is not available after setup." >&2
    exit 1
  fi
  $SUDO -H python3 -m pip install --break-system-packages pytesseract
else
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "python3 -m pip is not available." >&2
    exit 1
  fi
  $SUDO -H python3 -m pip install --break-system-packages -r requirements.txt
fi

python3 - <<'PY'
import cv2
import numpy
import pytesseract
import pytest

print("Python dependencies import correctly.")
print(f"OpenCV: {cv2.__version__}")
print(f"NumPy: {numpy.__version__}")
print(f"pytesseract: {pytesseract.get_tesseract_version()}")
print(f"pytest: {pytest.__version__}")
PY

echo
echo "Global Python dependencies installed."
echo "See the full CLI and examples with:"
echo "python3 app.py --help"
echo
echo "Example USB camera run:"
echo "python3 app.py --source usb --interval 3 --x1 177 --y1 171 --x2 349 --y2 201"
echo
echo "Example IP camera run:"
echo "python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --interval 3 --x1 177 --y1 171 --x2 349 --y2 201"
