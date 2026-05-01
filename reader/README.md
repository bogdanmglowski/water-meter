# Water Meter Camera OCR Logger

A minimal Python app that:
1. Captures an image from a USB or IP camera on a timer.
2. Saves the capture to `pictures/YYYY-MM-DD/`.
3. OCRs a numeric value from the image.
4. Appends `date time,value` rows to `readings.csv`.

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
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1'
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --interval 10
```

Crop OCR to a meter window by passing the top-left and bottom-right coordinates:

```bash
python3 app.py --source usb --x1 175 --y1 120 --x2 425 --y2 190
python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --x1 175 --y1 120 --x2 425 --y2 190
```

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
