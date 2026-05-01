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

source_kind="${READER_SOURCE:-usb}"
camera_index="${READER_CAMERA_INDEX:-0}"
ip_camera_url="${READER_IP_CAMERA_URL:-}"
interval_seconds="${READER_INTERVAL_SECONDS:-5}"
pictures_dir="${READER_PICTURES_DIR:-/data/pictures}"
csv_file="${READER_CSV_FILE:-/data/readings.csv}"
no_csv="${READER_NO_CSV:-true}"
persist_every="${READER_PERSIST_EVERY:-1}"
picture_type="${READER_PICTURE_TYPE:-auto}"
ocr_preprocess="${READER_OCR_PREPROCESS:-none}"
crop_output="${READER_CROP_OUTPUT:-}"
debug_output="${READER_DEBUG_OUTPUT:-}"
pg_source="${READER_PG_SOURCE:-reader-docker}"
pg_value_mode="${READER_PG_VALUE_MODE:-truncate}"
x1="${READER_X1:-}"
y1="${READER_Y1:-}"
x2="${READER_X2:-}"
y2="${READER_Y2:-}"

set -- \
    python3 app.py \
    --source "$source_kind" \
    --interval "$interval_seconds" \
    --pictures-dir "$pictures_dir" \
    --csv-file "$csv_file" \
    --persist-every "$persist_every" \
    --picture-type "$picture_type" \
    --ocr-preprocess "$ocr_preprocess"

if is_true "$no_csv"; then
    set -- "$@" --no-csv
fi

case "$source_kind" in
    usb)
        set -- "$@" --camera-index "$camera_index"
        ;;
    ip)
        require_non_empty "READER_IP_CAMERA_URL" "$ip_camera_url"
        set -- "$@" --ip-camera-url "$ip_camera_url"
        ;;
    *)
        echo "Unsupported READER_SOURCE: $source_kind" >&2
        exit 1
        ;;
esac

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

if [ -n "$debug_output" ]; then
    set -- "$@" --debug-output "$debug_output"
fi

if is_true "${READER_PG_WRITE:-true}"; then
    set -- "$@" --pg-write --pg-source "$pg_source" --pg-value-mode "$pg_value_mode"
fi

echo "Starting reader container (source=$source_kind interval=${interval_seconds}s pg_write=${READER_PG_WRITE:-true})"
exec "$@"
