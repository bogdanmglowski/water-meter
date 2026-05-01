# Water Meter USB Reader

Minimal Python app that:
1. Captures an image from a USB camera on a timer.
2. Saves the original frame to `pictures/YYYY-MM-DD/`.
3. Optionally writes the cropped rectangle to a fixed file.
4. Optionally inserts a fixed value of `1` into Water Meter's PostgreSQL table `meter_readings`.

Removed on purpose:
- IP camera URLs
- CSV output
- OCR and Tesseract
- picture types
- grayscale or other preprocessing

The reader always works on the original captured image. Cropping is only for exporting the selected rectangle.

## Requirements

- Python 3.10+
- USB camera accessible by OpenCV

Install Python deps:

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 app.py --help
```

Examples:

```bash
python3 app.py
python3 app.py --camera-index 0 --interval 30 --pictures-dir pictures
python3 app.py --interval 1 --persist-every 12
python3 app.py --x1 159 --y1 331 --x2 565 --y2 414 --crop-output meter-crop.png
python3 app.py --interval 5 --x1 159 --y1 331 --x2 565 --y2 414 --pg-write
```

Coordinate rules:

- `x1,y1` is the top-left corner.
- `x2,y2` is the bottom-right corner.
- All four coordinates must be provided together.
- The crop must stay inside the captured image bounds.

## PostgreSQL output

Use `--pg-write` to insert a fixed reading value of `1` into `meter_readings`.

Supported arguments:

- `--pg-write`: enables database inserts.
- `--pg-database-url`: PostgreSQL connection string. If omitted, the app falls back to `DATABASE_URL`.
- `--pg-source`: value written into the `source` column. Default: `reader`.

Notes:

- Inserts use `ON CONFLICT (recorded_at) DO UPDATE`.
- `meter_value_m3` is always written as `1`.

## Persist Every Nth Capture

Use `--persist-every N` to save only some pictures while still running the capture loop.

Example:

```bash
python3 app.py --interval 1 --persist-every 12
```

With `--persist-every 12`, the app saves the 1st, 13th, 25th, and later matching captures.

## Docker

Main stack profile:

```bash
./scripts/deploy.sh up --reader
```

Relevant `.env.production` settings:

```dotenv
READER_CAMERA_INDEX=0
READER_VIDEO_DEVICE=/dev/video0
READER_INTERVAL_SECONDS=5
READER_PERSIST_EVERY=1
READER_X1=159
READER_Y1=331
READER_X2=565
READER_Y2=414
READER_CROP_OUTPUT=/data/meter-crop.png
READER_PG_WRITE=true
READER_PG_SOURCE=reader-docker
```

Standalone compose in `reader/`:

```bash
cd reader
cp .env.example .env
docker compose up -d --build
```

For Linux USB cameras the container usually needs a mapping such as:

```yaml
devices:
  - /dev/video0:/dev/video0
```
