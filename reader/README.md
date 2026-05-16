# Water Meter USB Reader

Minimal Python app that:
1. Captures an image from a USB camera on a timer.
2. Saves the original frame to `pictures/YYYY-MM-DD/`.
3. Always writes the cropped rectangle to a fixed file and archives processed crops when the original frame is persisted.
4. Sends that crop to the Ollama API with model `glm-ocr`.
5. Optionally inserts the recognized meter value into Water Meter's PostgreSQL table `meter_readings`.

Register format:
- the OCR result is treated as register digits, not a decimal number
- the last three digits represent liters
- use `--ocr-append-digit 0` when the physical meter omits the final liter digit

Removed on purpose:
- IP camera URLs
- CSV output
- Tesseract
- picture types
- grayscale or other preprocessing

The reader always works on the original captured image. Cropping is required and the crop file is the input to Ollama OCR.

## Requirements

- Python 3.10+
- USB camera accessible by OpenCV
- reachable Ollama API
- `glm-ocr` pulled in Ollama

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
python3 app.py --camera-index 0 --interval 30 --pictures-dir pictures
python3 app.py --x1 159 --y1 331 --x2 565 --y2 414 --interval 1 --persist-every 12
python3 app.py --x1 159 --y1 331 --x2 565 --y2 414 --crop-output meter-crop.png
python3 app.py --interval 5 --x1 159 --y1 331 --x2 565 --y2 414 --pg-write
curl http://localhost:11434/api/generate -d '{"model":"glm-ocr","prompt":"Text Recognition:","images":["<base64-image>"],"stream":false}'
```

Coordinate rules:

- `x1,y1` is the top-left corner.
- `x2,y2` is the bottom-right corner.
- All four coordinates must be provided together.
- The crop must stay inside the captured image bounds.
- Crop coordinates are required.

## OCR

Each cycle does this:

1. Capture original frame.
2. Save crop to `--crop-output`.
3. Send the crop to `OLLAMA_BASE_URL/api/generate` with model `glm-ocr`.
4. Extract the first numeric token from the response and keep digits only.

When the original frame is persisted, the processed crop is also archived into `processed/YYYY-MM-DD/`.

If `--ocr-append-digit` is set, that digit is appended before logging and PostgreSQL insert.

## PostgreSQL output

Use `--pg-write` to insert the recognized meter value into `meter_readings`.

Supported arguments:

- `--pg-write`: enables database inserts.
- `--pg-database-url`: PostgreSQL connection string. If omitted, the app falls back to `DATABASE_URL`.
- `--pg-source`: value written into the `source` column. Default: `reader`.
- `--pg-anomaly-threshold`: skip inserts when the reading jumps above the immediately previous reading by more than this amount, or when the delta is negative. Default: `100`.
- `--ocr-append-digit`: append one trailing digit to the OCR result before logging and storing it.

Notes:

- Inserts use `ON CONFLICT (recorded_at) DO UPDATE`.
- OCR uses the crop file written to `--crop-output`.
- Stored values keep the full register precision, with the last three digits representing liters.
- Default `OLLAMA_BASE_URL` is `http://127.0.0.1:11434` for host runs.

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

Relevant root `.env` settings:

- use the `READER_*` and `OLLAMA_BASE_URL` entries from the root `.env.example`
- adjust `READER_VIDEO_DEVICE` and crop coordinates for the target host and camera

Docker note:

- The reader talks to Ollama over HTTP.
- The compose files already expose `host.docker.internal` to the container and default `OLLAMA_BASE_URL` to `http://host.docker.internal:11434`.
- Ollama on the host must accept connections from Docker, not only `127.0.0.1`.

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
