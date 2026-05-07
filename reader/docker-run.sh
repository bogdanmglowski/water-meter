#!/bin/sh
set -eu

is_true() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

require_non_empty() {
    name="$1"
    value="$2"
    if [ -z "$value" ]; then
        echo "Missing required environment variable: $name" >&2
        exit 1
    fi
}

camera_index="${READER_CAMERA_INDEX:-0}"
interval_seconds="${READER_INTERVAL_SECONDS:-5}"
pictures_dir="${READER_PICTURES_DIR:-/data/pictures}"
processed_pictures_dir="${READER_PROCESSED_PICTURES_DIR:-/data/processed}"
persist_every="${READER_PERSIST_EVERY:-1}"
crop_output="${READER_CROP_OUTPUT:-}"
pg_source="${READER_PG_SOURCE:-reader-docker}"
pg_anomaly_threshold="${READER_PG_ANOMALY_THRESHOLD:-100}"
ocr_append_digit="${READER_OCR_APPEND_DIGIT:-}"
control_bind="${READER_CONTROL_BIND:-}"
x1="${READER_X1:-}"
y1="${READER_Y1:-}"
x2="${READER_X2:-}"
y2="${READER_Y2:-}"

set -- \
    python3 app.py \
    --camera-index "$camera_index" \
    --interval "$interval_seconds" \
    --pictures-dir "$pictures_dir" \
    --processed-pictures-dir "$processed_pictures_dir" \
    --persist-every "$persist_every"

if [ -n "$x1$y1$x2$y2" ]; then
    require_non_empty "READER_X1" "$x1"
    require_non_empty "READER_Y1" "$y1"
    require_non_empty "READER_X2" "$x2"
    require_non_empty "READER_Y2" "$y2"
    set -- "$@" --x1 "$x1" --y1 "$y1" --x2 "$x2" --y2 "$y2"
fi

if [ -n "$crop_output" ]; then
    set -- "$@" --crop-output "$crop_output"
fi

if is_true "${READER_PG_WRITE:-true}"; then
    set -- "$@" --pg-write --pg-source "$pg_source" --pg-anomaly-threshold "$pg_anomaly_threshold"
fi

if [ -n "$ocr_append_digit" ]; then
    set -- "$@" --ocr-append-digit "$ocr_append_digit"
fi

if [ -n "$control_bind" ]; then
    set -- "$@" --control-bind "$control_bind"
fi

echo "Starting reader container (source=usb camera_index=${camera_index} interval=${interval_seconds}s pg_write=${READER_PG_WRITE:-true})"
exec "$@"
