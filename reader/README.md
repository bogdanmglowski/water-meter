# Water Meter Camera OCR Logger

A minimal Python app that:
1. Captures an image from a USB or IP camera on a timer.
2. Saves the capture to `pictures/YYYY-MM-DD/`.
3. OCRs a numeric value from the image.
4. Appends `date time,value` rows to `readings.csv`.
5. Optionally inserts the reading into Water Meter's PostgreSQL table `meter_readings`.

Without cropping it stores the raw camera frame as `.jpg`. When a crop rectangle is configured, it stores the preprocessed OCR input as `.png`, so the saved file matches the image used to read the digits.
Live OCR always runs on every interval. You can reduce disk usage with `--persist-every N` to save only every Nth live capture while still OCR'ing and logging every cycle.

## Requirements

- Python 3.10+
- System `tesseract` binary installed
- Camera accessible by OpenCV: a local USB camera index or an IP camera stream such as RTSP

Install Python deps:

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 app.py --help
```

Common live capture examples:

```bash
python3 app.py --source usb
python3 app.py --source usb --camera-index 0 --interval 30 --pictures-dir pictures --csv-file readings.csv
python3 app.py --source usb --interval 1 --persist-every 12
python3 app.py --source usb --x1 159 --y1 331 --x2 565 --y2 414 --crop-output meter-crop.png
python3 app.py --source usb --interval 5 --x1 159 --y1 331 --x2 565 --y2 414 --pg-write
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1'
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --interval 10
```

Crop OCR to a meter window by passing the top-left and bottom-right coordinates:

```bash
python3 app.py --source usb --x1 175 --y1 120 --x2 425 --y2 190
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --x1 175 --y1 120 --x2 425 --y2 190
```

Write to the Water Meter PostgreSQL database as well as CSV:

```bash
python3 app.py \
  --source usb \
  --interval 5 \
  --x1 159 --y1 331 --x2 565 --y2 414 \
  --crop-output meter-crop.png \
  --pg-write \
  --pg-database-url 'postgres://meter:meter@localhost:5432/water_meter' \
  --pg-source reader-usb
```

If `DATABASE_URL` is already exported in the shell or loaded from the project `.env`, `--pg-database-url` can be omitted.

Source selection rules:

- `--source usb` opens a local camera by OpenCV index via `--camera-index`.
- `--source ip` opens a network camera stream via `--ip-camera-url` or `--rtsp-url`.
- For `--source ip`, the app reconnects to the stream on each capture cycle to avoid stale buffered RTSP frames.
- In live mode, `--ip-camera-url` is required for `--source ip`.
- In `--debug-picture` mode, live source options are ignored.

Coordinate rules:

- `x1,y1` is the top-left corner of the OCR rectangle.
- `x2,y2` is the bottom-right corner of the OCR rectangle.
- All four coordinates must be provided together.
- The crop must stay inside the captured image bounds.

The OCR path preprocesses the cropped region before sending it to Tesseract, which works better for meter windows that mix white and red digits.

## Debug mode

Run one OCR pass against an existing image and exit:

```bash
python3 app.py \
  --debug-picture pictures/2026-03-17/sample.jpg \
  --x1 175 --y1 120 --x2 425 --y2 190
```

Persist debug artifacts while using either a live camera or `--debug-picture`:

```bash
python3 app.py \
  --debug-picture pictures/2026-03-17/sample.jpg \
  --x1 175 --y1 120 --x2 425 --y2 190 \
  --debug-output debug
```

`--debug-output` writes:

- `*_annotated.png`: original image with the crop rectangle drawn on it.
- `*_cropped.png`: the exact rectangle sent into OCR preprocessing.
- `*_ocr_input.png`: the thresholded image passed to Tesseract.

The app logs the selected live source at startup. If the source URL contains credentials, the password is masked in the console output.

## PostgreSQL output

Use `--pg-write` to insert each successful OCR reading into the same `meter_readings` table that the Rust backend reads.

Supported arguments:

- `--pg-write`: enables database inserts in addition to the existing CSV append.
- `--crop-output`: writes the latest cropped OCR window to a fixed path such as `meter-crop.png`.
- `--pg-database-url`: PostgreSQL connection string. If omitted, the app falls back to `DATABASE_URL`.
- `--pg-source`: value written into the `source` column. Default: `reader`.
- `--pg-value-mode`: maps OCR text into Water Meter's integer `meter_value_m3` column.

`--pg-value-mode` options:

- `truncate`: stores `12345.67` as `12345`. This is the safest default when the red fractional wheels are visible in the crop.
- `round`: stores `12345.67` as `12346`.
- `reject`: fails the cycle when OCR returns a fractional value.

Important integration note:

- The current Water Meter schema stores `meter_value_m3` as `BIGINT`, so PostgreSQL inserts are integer-only.
- If your crop includes decimal wheels, `truncate` is usually the right choice because the dashboard currently works on whole cubic meters.
- Failed OCR values are still written as empty CSV rows, but they are not inserted into PostgreSQL.
- Inserts use `ON CONFLICT (recorded_at) DO UPDATE`, so rerunning the same second updates that row instead of crashing on the unique timestamp constraint.
- `--crop-output` is only available in live capture mode and requires crop coordinates.
- `--pg-write` is only available in live capture mode; it is intentionally rejected with `--debug-picture`.

## CSV format

Header:

```text
date time,value
```

If OCR fails to find a numeric token, the app writes an empty value for that timestamp.

## Persist Every Nth Capture

Use `--persist-every N` in live mode to save only some of the pictures while still running OCR and appending CSV rows on every interval.

Example:

```bash
python3 app.py --source usb --interval 1 --persist-every 12
```

With `--persist-every 12`, the app saves the 1st, 13th, 25th, and later matching live captures. The 11 cycles in between still capture, crop, OCR, and write CSV rows, but they do not write an image file.

## More examples

```bash
python3 app.py \
  --source usb \
  --interval 3 \
  --x1 177 --y1 171 --x2 349 --y2 201

python3 app.py \
  --source ip \
  --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' \
  --x1 177 --y1 171 --x2 349 --y2 201 \
  --debug-output pictures/debug

python3 app.py \
  --debug-picture pictures/2026-03-17/2026-03-17_18-29-15.jpg \
  --x1 177 --y1 171 --x2 349 --y2 201 \
  --debug-output pictures/debug
```

## Docker option for production

One practical option is to run `reader` as a separate container in the same Docker network as `db`, instead of baking it into the existing backend/frontend services.

The repository now includes a ready `reader/Dockerfile`, a container entrypoint [docker-run.sh](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/reader/docker-run.sh), and two compose options:

1. Main production stack profile:

```bash
./scripts/deploy.sh up --reader
```

This uses the `reader` profile already wired into [infra/docker-compose.yml](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/infra/docker-compose.yml). Configure it through `.env.production`, for example:

```dotenv
READER_SOURCE=usb
READER_CAMERA_INDEX=0
READER_VIDEO_DEVICE=/dev/video0
READER_INTERVAL_SECONDS=5
READER_X1=159
READER_Y1=331
READER_X2=565
READER_Y2=414
READER_CROP_OUTPUT=/data/meter-crop.png
READER_PG_WRITE=true
READER_PG_SOURCE=reader-docker
READER_PG_VALUE_MODE=truncate
```

For an IP camera in the production stack:

```dotenv
READER_SOURCE=ip
READER_IP_CAMERA_URL=rtsp://admin:password@192.168.10.31:554/stream1
READER_VIDEO_DEVICE=/dev/null
```

2. Standalone compose in `reader/`:

```bash
cd reader
cp .env.example .env
docker compose up -d --build
```

The standalone compose file is [reader/docker-compose.yml](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/reader/docker-compose.yml). It joins the existing Docker network from the main Water Meter stack, so the main stack must already be running and expose the network `water-meter_default`.

If your main stack uses a different network name, override it:

```bash
cd reader
WATER_METER_NETWORK=my-stack_default docker compose up -d --build
```

For a USB camera on Linux, the container usually also needs a device mapping such as:

```yaml
    devices:
      - /dev/video0:/dev/video0
```

The standalone compose already contains that mapping and exposes it through `READER_VIDEO_DEVICE`. For an IP camera, set `READER_SOURCE=ip`, set `READER_IP_CAMERA_URL`, and use `READER_VIDEO_DEVICE=/dev/null`.
