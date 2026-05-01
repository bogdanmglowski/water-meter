from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    import cv2
except ModuleNotFoundError as exc:
    cv2 = None
    _CV2_IMPORT_ERROR = exc
else:
    _CV2_IMPORT_ERROR = None

try:
    import pytesseract
except ModuleNotFoundError as exc:
    pytesseract = None
    _PYTESSERACT_IMPORT_ERROR = exc
else:
    _PYTESSERACT_IMPORT_ERROR = None

try:
    import psycopg
except ModuleNotFoundError as exc:
    psycopg = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None

NUMERIC_TOKEN_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789.,"
PICTURE_TYPES = ("auto", "raw", "cropped", "annotated", "ocr_input")
OCR_PREPROCESS_MODES = ("auto", "none")
POSTGRES_VALUE_MODES = ("truncate", "round", "reject")
ANNOTATION_COLOR = (0, 255, 0)
ANNOTATION_THICKNESS = 2
CAMERA_SOURCES = ("usb", "ip")
IP_CAMERA_BUFFER_SIZE = 1
IP_CAMERA_FLUSH_GRABS = 2


class AppHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    pass


@dataclass(frozen=True)
class CropRect:
    x1: int
    y1: int
    x2: int
    y2: int

    def validate(self) -> None:
        if self.x1 < 0 or self.y1 < 0:
            raise ValueError("Crop coordinates must be non-negative")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("Crop rectangle must satisfy x2 > x1 and y2 > y1")


@dataclass(frozen=True)
class CameraSource:
    kind: str
    target: int | str


@dataclass(frozen=True)
class PostgresTarget:
    database_url: str
    source: str
    value_mode: str


HELP_EPILOG = """Examples:
  USB camera with the default webcam:
    python3 app.py --source usb

  USB camera with crop coordinates and a faster polling interval:
    python3 app.py --source usb --camera-index 0 --interval 3 --x1 177 --y1 171 --x2 349 --y2 201

  USB camera with OCR every second but only every 12th picture persisted:
    python3 app.py --source usb --interval 1 --persist-every 12

  USB camera with a fixed latest-crop output file:
    python3 app.py --source usb --x1 159 --y1 331 --x2 565 --y2 414 --crop-output meter-crop.png

  USB camera with PostgreSQL writes enabled:
    python3 app.py --source usb --interval 5 --x1 159 --y1 331 --x2 565 --y2 414 --pg-write

  USB camera with CSV disabled:
    python3 app.py --source usb --no-csv --pg-write

  IP camera over RTSP:
    python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1'

  IP camera with debug artifacts enabled:
    python3 app.py --source ip --ip-camera-url 'rtsp://admin:password@192.168.10.31:554/stream1' --debug-output pictures/debug

  Single OCR run against an existing image:
    python3 app.py --debug-picture pictures/2026-03-17/sample.jpg --x1 175 --y1 120 --x2 425 --y2 190
"""


def find_project_python() -> Path | None:
    for path in (Path(".venv/bin/python"), Path("venv/bin/python")):
        if path.exists():
            return path
    return None


def ensure_runtime_dependencies() -> None:
    missing_packages: list[str] = []
    if _CV2_IMPORT_ERROR is not None:
        missing_packages.append("opencv-python")
    if _PYTESSERACT_IMPORT_ERROR is not None:
        missing_packages.append("pytesseract")

    if not missing_packages:
        return

    message = f"Missing Python dependencies: {', '.join(missing_packages)}."
    project_python = find_project_python()
    if project_python is not None:
        message += (
            f" Use `{project_python} app.py ...` or activate the virtualenv with "
            f"`source {project_python.parent / 'activate'}`."
        )
    message += " To install them into the current interpreter, run `python3 -m pip install -r requirements.txt`."
    raise RuntimeError(message)


def ensure_postgres_dependencies() -> None:
    if _PSYCOPG_IMPORT_ERROR is None:
        return

    message = "Missing Python dependency: psycopg[binary]."
    project_python = find_project_python()
    if project_python is not None:
        message += (
            f" Use `{project_python} app.py ...` or activate the virtualenv with "
            f"`source {project_python.parent / 'activate'}`."
        )
    message += " To install it into the current interpreter, run `python3 -m pip install -r requirements.txt`."
    raise RuntimeError(message)


def normalize_ocr_text(text: str) -> str | None:
    """Return the first number-like token from OCR text, normalized to dot decimal."""
    if not text:
        return None

    match = NUMERIC_TOKEN_PATTERN.search(text)
    if not match:
        return None

    return match.group(0).replace(",", ".")


def mask_url_credentials(url: str) -> str:
    parts = urlsplit(url)
    try:
        username = parts.username
        password = parts.password
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return url

    if username is None and password is None:
        return url

    auth = ""
    if username is not None:
        auth = username
        if password is not None:
            auth += ":***"
        auth += "@"

    host = hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"

    masked_netloc = f"{auth}{host}"
    return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))


def format_camera_source(camera_source: CameraSource) -> str:
    if camera_source.kind == "usb":
        return f"usb(index={camera_source.target})"
    return f"ip(url={mask_url_credentials(str(camera_source.target))})"


def format_postgres_target(target: PostgresTarget) -> str:
    return f"enabled(source={target.source}, value_mode={target.value_mode})"


def ensure_csv_header(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date time", "value"])


def append_csv_row(csv_path: Path, timestamp: datetime, value: str | None) -> None:
    ensure_csv_header(csv_path)

    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([timestamp.strftime("%Y-%m-%d %H:%M:%S"), value or ""])


def convert_ocr_value_to_meter_value(value: str, value_mode: str) -> int:
    numeric = Decimal(value)

    if value_mode == "truncate":
        return int(numeric)
    if value_mode == "round":
        return int(numeric.to_integral_value(rounding=ROUND_HALF_UP))
    if value_mode == "reject":
        integral = numeric.to_integral_value()
        if numeric != integral:
            raise ValueError(
                f"OCR value {value} includes a fractional component; use --pg-value-mode truncate or round"
            )
        return int(integral)

    raise ValueError(f"Unsupported PostgreSQL value mode: {value_mode}")


def normalize_postgres_timestamp(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.astimezone().astimezone(timezone.utc)
    return timestamp.astimezone(timezone.utc)


class PostgresWriter:
    def __init__(self, target: PostgresTarget) -> None:
        self.target = target
        self._connection: Any | None = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connect(self) -> Any:
        ensure_postgres_dependencies()
        try:
            return psycopg.connect(self.target.database_url, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            masked_url = mask_url_credentials(self.target.database_url)
            raise RuntimeError(f"Could not connect to PostgreSQL {masked_url}: {exc}") from exc

    def _ensure_connection(self) -> Any:
        if self._connection is None or getattr(self._connection, "closed", False):
            self._connection = self._connect()
        return self._connection

    def connect(self) -> None:
        self._ensure_connection()

    def persist(self, timestamp: datetime, value: str | None) -> None:
        if value is None:
            return

        recorded_at = normalize_postgres_timestamp(timestamp)
        meter_value_m3 = convert_ocr_value_to_meter_value(value, self.target.value_mode)
        connection = self._ensure_connection()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (recorded_at) DO UPDATE
                    SET meter_value_m3 = EXCLUDED.meter_value_m3,
                        source = EXCLUDED.source
                    """,
                    (recorded_at, meter_value_m3, self.target.source),
                )
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RuntimeError(f"Failed to persist reading to PostgreSQL: {exc}") from exc


def build_capture_image_path(
    pictures_root: Path,
    timestamp: datetime,
    picture_type: str,
) -> Path:
    day_dir = pictures_root / timestamp.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".jpg" if picture_type == "raw" else ".png"
    return day_dir / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}{suffix}"


def build_debug_picture_save_path(
    pictures_root: Path,
    timestamp: datetime,
    source_path: Path,
) -> Path:
    day_dir = pictures_root / timestamp.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    suffix = source_path.suffix or ".png"
    return day_dir / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}{suffix}"


def write_crop_output(crop_output_path: Path, cropped: cv2.typing.MatLike) -> None:
    crop_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_image(crop_output_path, cropped)


def save_debug_picture_input(
    source_path: Path,
    pictures_root: Path,
    timestamp: datetime,
) -> Path:
    saved_path = build_debug_picture_save_path(pictures_root, timestamp, source_path)
    shutil.copyfile(source_path, saved_path)
    return saved_path


def resolve_picture_type(
    picture_type: str,
    *,
    crop_rect: CropRect | None,
    debug_picture: bool,
) -> str:
    if picture_type != "auto":
        return picture_type
    if debug_picture:
        return "raw"
    return "ocr_input" if crop_rect is not None else "raw"


def capture_and_save_image(
    camera: cv2.VideoCapture | None,
    pictures_root: Path,
    timestamp: datetime,
    camera_source: CameraSource | None = None,
    crop_rect: CropRect | None = None,
    picture_type: str = "auto",
    ocr_preprocess: str = "auto",
    persist_image: bool = True,
) -> tuple[
    Path | None,
    cv2.typing.MatLike,
    cv2.typing.MatLike,
    cv2.typing.MatLike,
    cv2.typing.MatLike,
    CropRect | None,
    str,
]:
    effective_camera_source = camera_source or CameraSource("usb", 0)

    if effective_camera_source.kind == "ip":
        temp_camera = open_camera(effective_camera_source)
        try:
            frame = read_frame(temp_camera, effective_camera_source)
        finally:
            temp_camera.release()
    else:
        if camera is None:
            raise RuntimeError("USB camera capture requires an opened camera handle")
        frame = read_frame(camera, effective_camera_source)

    actual_picture_type = resolve_picture_type(
        picture_type,
        crop_rect=crop_rect,
        debug_picture=False,
    )

    if actual_picture_type in {"cropped", "annotated"} and crop_rect is None:
        raise ValueError("--picture-type cropped/annotated requires crop coordinates")

    if actual_picture_type == "raw":
        image_to_save = frame
        effective_crop_rect = crop_rect
        cropped = crop_image(frame, crop_rect)
        prepared = build_ocr_input(cropped, ocr_preprocess)
    elif actual_picture_type == "cropped":
        image_to_save = crop_image(frame, crop_rect)
        effective_crop_rect = None
        cropped = image_to_save
        prepared = build_ocr_input(cropped, ocr_preprocess)
    elif actual_picture_type == "annotated":
        image_to_save = annotate_image(frame, crop_rect)
        effective_crop_rect, cropped = extract_cropped_image_from_annotated_image(image_to_save)
        prepared = build_ocr_input(cropped, ocr_preprocess)
    elif actual_picture_type == "ocr_input":
        cropped = crop_image(frame, crop_rect)
        prepared = build_ocr_input(cropped, ocr_preprocess)
        image_to_save = prepared
        effective_crop_rect = crop_rect
    else:
        raise ValueError(f"Unsupported picture type: {actual_picture_type}")

    image_path: Path | None = None
    if persist_image:
        image_path = build_capture_image_path(pictures_root, timestamp, actual_picture_type)
        write_image(image_path, image_to_save)

    return image_path, frame, image_to_save, cropped, prepared, effective_crop_rect, actual_picture_type


def write_image(image_path: Path, image: cv2.typing.MatLike) -> None:
    ensure_runtime_dependencies()
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(image_path), image):
        raise RuntimeError(f"Failed to write image to {image_path}")


def read_frame(camera: cv2.VideoCapture, camera_source: CameraSource) -> cv2.typing.MatLike:
    if camera_source.kind == "ip":
        for _ in range(IP_CAMERA_FLUSH_GRABS):
            if not camera.grab():
                break

    ok, frame = camera.read()
    if not ok or frame is None:
        raise RuntimeError("Camera capture failed")

    return frame


def crop_image(image: cv2.typing.MatLike, crop_rect: CropRect | None) -> cv2.typing.MatLike:
    if crop_rect is None:
        return image

    crop_rect.validate()

    height, width = image.shape[:2]
    if crop_rect.x2 > width or crop_rect.y2 > height:
        raise ValueError(
            "Crop rectangle is outside image bounds "
            f"(image={width}x{height}, crop=({crop_rect.x1},{crop_rect.y1})-"
            f"({crop_rect.x2},{crop_rect.y2}))"
        )

    return image[crop_rect.y1 : crop_rect.y2, crop_rect.x1 : crop_rect.x2]


def add_ocr_border(image: cv2.typing.MatLike) -> cv2.typing.MatLike:
    height = image.shape[0]
    x_pad = min(12, max(4, height // 5))
    return cv2.copyMakeBorder(
        image,
        0,
        0,
        x_pad,
        x_pad,
        cv2.BORDER_CONSTANT,
        value=255,
    )


def prepare_image_for_ocr(image: cv2.typing.MatLike) -> cv2.typing.MatLike:
    ensure_runtime_dependencies()
    if len(image.shape) == 2:
        gray = image.astype("uint8")
    else:
        # Ignoring the red channel keeps both black and red wheels dark,
        # while white digits stay bright.
        gray = image[:, :, :2].max(axis=2).astype("uint8")

    bordered = add_ocr_border(gray)
    enlarged = cv2.resize(bordered, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(enlarged, (5, 5), 0)
    _, thresholded = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return thresholded


def build_ocr_input(image: cv2.typing.MatLike, ocr_preprocess: str) -> cv2.typing.MatLike:
    if ocr_preprocess == "auto":
        return prepare_image_for_ocr(image)
    if ocr_preprocess == "none":
        return image
    raise ValueError(f"Unsupported OCR preprocess mode: {ocr_preprocess}")


def annotate_image(image: cv2.typing.MatLike, crop_rect: CropRect) -> cv2.typing.MatLike:
    annotated = image.copy()
    cv2.rectangle(
        annotated,
        (crop_rect.x1, crop_rect.y1),
        (crop_rect.x2 - 1, crop_rect.y2 - 1),
        ANNOTATION_COLOR,
        ANNOTATION_THICKNESS,
    )
    return annotated


def find_crop_rect_in_annotated_image(image: cv2.typing.MatLike) -> CropRect:
    ensure_runtime_dependencies()
    if len(image.shape) != 3 or image.shape[2] < 3:
        raise ValueError("Annotated pictures must be color images")

    mask = cv2.inRange(image, ANNOTATION_COLOR, ANNOTATION_COLOR)
    points = cv2.findNonZero(mask)
    if points is None:
        raise ValueError("Could not find a crop rectangle in the annotated debug picture")

    x, y, width, height = cv2.boundingRect(points)
    image_height, image_width = image.shape[:2]

    x1 = 0 if x == 0 else x + 1
    y1 = 0 if y == 0 else y + 1
    x2 = image_width if x + width == image_width else x + width - 1
    y2 = image_height if y + height == image_height else y + height - 1

    crop_rect = CropRect(x1, y1, x2, y2)
    crop_rect.validate()
    return crop_rect


def extract_cropped_image_from_annotated_image(
    image: cv2.typing.MatLike,
) -> tuple[CropRect, cv2.typing.MatLike]:
    crop_rect = find_crop_rect_in_annotated_image(image)
    cleaned = image.copy()
    mask = cv2.inRange(image, ANNOTATION_COLOR, ANNOTATION_COLOR)
    cleaned[mask != 0] = 255
    return crop_rect, crop_image(cleaned, crop_rect)


def read_image(image_path: Path) -> cv2.typing.MatLike:
    ensure_runtime_dependencies()
    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Failed to read image for OCR: {image_path}")
    return image


def build_debug_image_paths(
    source_path: Path,
    debug_output_dir: Path,
    crop_rect: CropRect | None,
) -> dict[str, Path]:
    stem = source_path.stem
    paths = {
        "cropped": debug_output_dir / f"{stem}_cropped.png",
        "ocr_input": debug_output_dir / f"{stem}_ocr_input.png",
    }
    if crop_rect is not None:
        paths["annotated"] = debug_output_dir / f"{stem}_annotated.png"
    return paths


def save_debug_images(
    source_path: Path,
    image: cv2.typing.MatLike,
    cropped: cv2.typing.MatLike,
    prepared: cv2.typing.MatLike,
    crop_rect: CropRect | None,
    debug_output_dir: Path,
    *,
    annotated_image: cv2.typing.MatLike | None = None,
) -> dict[str, Path]:
    debug_paths = build_debug_image_paths(source_path, debug_output_dir, crop_rect)

    if crop_rect is not None:
        annotated = annotated_image if annotated_image is not None else annotate_image(image, crop_rect)
        write_image(debug_paths["annotated"], annotated)

    write_image(debug_paths["cropped"], cropped)
    write_image(debug_paths["ocr_input"], prepared)
    return debug_paths


def extract_value_from_prepared_image(image: cv2.typing.MatLike) -> str | None:
    ensure_runtime_dependencies()
    try:
        raw_text = pytesseract.image_to_string(image, config=OCR_CONFIG)
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "The `tesseract` executable is not installed or not on PATH. Install the system package and try again."
        ) from exc
    return normalize_ocr_text(raw_text)


def extract_value_from_image(
    image_path: Path,
    crop_rect: CropRect | None = None,
    debug_output_dir: Path | None = None,
    picture_type: str = "raw",
    ocr_preprocess: str = "auto",
) -> str | None:
    image = read_image(image_path)
    actual_picture_type = resolve_picture_type(
        picture_type,
        crop_rect=crop_rect,
        debug_picture=True,
    )

    annotated_image = None
    if actual_picture_type == "raw":
        effective_crop_rect = crop_rect
        cropped = crop_image(image, crop_rect)
        prepared = build_ocr_input(cropped, ocr_preprocess)
    elif actual_picture_type == "cropped":
        effective_crop_rect = None
        cropped = image
        prepared = build_ocr_input(cropped, ocr_preprocess)
    elif actual_picture_type == "annotated":
        effective_crop_rect, cropped = extract_cropped_image_from_annotated_image(image)
        prepared = build_ocr_input(cropped, ocr_preprocess)
        annotated_image = image
    elif actual_picture_type == "ocr_input":
        effective_crop_rect = None
        cropped = image
        prepared = image
    else:
        raise ValueError(f"Unsupported picture type: {actual_picture_type}")

    if debug_output_dir is not None:
        save_debug_images(
            image_path,
            image,
            cropped,
            prepared,
            effective_crop_rect,
            debug_output_dir,
            annotated_image=annotated_image,
        )
    return extract_value_from_prepared_image(prepared)


def run_capture_cycle(
    camera: cv2.VideoCapture | None,
    pictures_root: Path,
    csv_path: Path,
    *,
    timestamp: datetime | None = None,
    camera_source: CameraSource | None = None,
    crop_rect: CropRect | None = None,
    picture_type: str = "auto",
    ocr_preprocess: str = "auto",
    debug_output_dir: Path | None = None,
    persist_image: bool = True,
    write_csv: bool = True,
    crop_output_path: Path | None = None,
    postgres_writer: PostgresWriter | None = None,
    ocr_func=extract_value_from_prepared_image,
) -> tuple[Path | None, str | None, datetime]:
    ensure_runtime_dependencies()
    ts = timestamp or datetime.now()
    image_path, image, saved_image, cropped, prepared, effective_crop_rect, actual_picture_type = capture_and_save_image(
        camera,
        pictures_root,
        ts,
        camera_source=camera_source,
        crop_rect=crop_rect,
        picture_type=picture_type,
        ocr_preprocess=ocr_preprocess,
        persist_image=persist_image,
    )
    if debug_output_dir is not None and image_path is not None:
        save_debug_images(
            image_path,
            image,
            cropped,
            prepared,
            effective_crop_rect,
            debug_output_dir,
            annotated_image=saved_image if actual_picture_type == "annotated" else None,
        )
    if crop_output_path is not None:
        write_crop_output(crop_output_path, cropped)
    value = ocr_func(prepared)
    if write_csv:
        append_csv_row(csv_path, ts, value)
    if postgres_writer is not None:
        postgres_writer.persist(ts, value)
    return image_path, value, ts


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture images from a USB or IP camera, OCR the water meter value, and optionally append rows to CSV.",
        formatter_class=AppHelpFormatter,
        epilog=HELP_EPILOG,
    )

    source_group = parser.add_argument_group("capture source")
    source_group.add_argument(
        "--source",
        "--camera-source",
        dest="camera_source",
        choices=CAMERA_SOURCES,
        default="usb",
        help="Capture source type: `usb` opens a local webcam by index, `ip` opens a network camera stream URL.",
    )
    source_group.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV camera index used when `--source usb`.",
    )
    source_group.add_argument(
        "--ip-camera-url",
        "--rtsp-url",
        dest="ip_camera_url",
        help=(
            "IP camera stream URL used when `--source ip`, for example "
            "`rtsp://admin:password@192.168.10.31:554/stream1`. "
            "The app reconnects to this stream for each capture to avoid stale buffered frames."
        ),
    )

    schedule_group = parser.add_argument_group("schedule and outputs")
    schedule_group.add_argument(
        "--interval-seconds",
        "--interval",
        type=float,
        default=30,
        help="Seconds to wait between live capture cycles.",
    )
    schedule_group.add_argument(
        "--pictures-dir",
        type=Path,
        default=Path("pictures"),
        help="Root directory where captured and copied pictures are stored.",
    )
    schedule_group.add_argument(
        "--csv-file",
        type=Path,
        default=Path("readings.csv"),
        help="CSV file where `date time,value` rows are appended unless `--no-csv` is set.",
    )
    schedule_group.add_argument(
        "--no-csv",
        action="store_true",
        help="Disable CSV output. OCR, picture persistence, and optional PostgreSQL writes still run.",
    )
    schedule_group.add_argument(
        "--persist-every",
        type=int,
        default=1,
        help=(
            "Persist the captured picture every N live capture cycles while OCR still runs on every cycle. "
            "The first live capture is always persisted."
        ),
    )
    schedule_group.add_argument(
        "--crop-output",
        type=Path,
        help=(
            "Also write the current cropped OCR region to this fixed file path on each live capture cycle. "
            "Requires crop coordinates."
        ),
    )

    crop_group = parser.add_argument_group("crop and OCR")
    crop_group.add_argument("--x1", type=int, help="Left X coordinate of the OCR crop rectangle.")
    crop_group.add_argument("--y1", type=int, help="Top Y coordinate of the OCR crop rectangle.")
    crop_group.add_argument("--x2", type=int, help="Right X coordinate of the OCR crop rectangle.")
    crop_group.add_argument("--y2", type=int, help="Bottom Y coordinate of the OCR crop rectangle.")
    crop_group.add_argument(
        "--ocr-preprocess",
        choices=OCR_PREPROCESS_MODES,
        default="auto",
        help=(
            "How to transform the cropped OCR region before Tesseract: `auto` applies the current grayscale, blur, "
            "and threshold pipeline; `none` sends the raw crop directly to OCR."
        ),
    )

    debug_group = parser.add_argument_group("debug and offline processing")
    debug_group.add_argument(
        "--debug-picture",
        type=Path,
        help="Use an existing image for a single OCR run and exit. Live camera source options are ignored when this is set.",
    )
    debug_group.add_argument(
        "--picture-type",
        "--type",
        "--debug-picture-type",
        dest="picture_type",
        choices=PICTURE_TYPES,
        default="auto",
        help=(
            "Controls which picture variant is saved and OCR'd: `raw`, `cropped`, `annotated`, `ocr_input`, "
            "or `auto`. `auto` saves the raw frame when no crop is configured, otherwise it saves the prepared OCR input."
        ),
    )
    debug_group.add_argument(
        "--debug-output",
        type=Path,
        help="Directory where debug artifacts such as annotated, cropped, and OCR-input images are written.",
    )

    postgres_group = parser.add_argument_group("postgres output")
    postgres_group.add_argument(
        "--pg-write",
        action="store_true",
        help=(
            "Insert successful OCR readings into the Water Meter PostgreSQL table `meter_readings`."
        ),
    )
    postgres_group.add_argument(
        "--pg-database-url",
        help="PostgreSQL connection string. Defaults to the `DATABASE_URL` environment variable when set.",
    )
    postgres_group.add_argument(
        "--pg-source",
        default="reader",
        help="Value written into the `source` column for PostgreSQL inserts.",
    )
    postgres_group.add_argument(
        "--pg-value-mode",
        choices=POSTGRES_VALUE_MODES,
        default="truncate",
        help=(
            "How OCR values map into Water Meter's integer `meter_value_m3` column: `truncate` drops the fraction, "
            "`round` uses half-up rounding, and `reject` fails on fractional OCR output."
        ),
    )
    return parser


def parse_crop_rect(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CropRect | None:
    values = (args.x1, args.y1, args.x2, args.y2)
    if not any(value is not None for value in values):
        return None

    if not all(value is not None for value in values):
        parser.error("When using crop coordinates, provide all of --x1, --y1, --x2, and --y2")

    crop_rect = CropRect(args.x1, args.y1, args.x2, args.y2)
    try:
        crop_rect.validate()
    except ValueError as exc:
        parser.error(str(exc))

    return crop_rect


def parse_debug_picture(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path | None:
    if args.debug_picture is None:
        return None
    if not args.debug_picture.exists():
        parser.error(f"--debug-picture does not exist: {args.debug_picture}")
    if not args.debug_picture.is_file():
        parser.error(f"--debug-picture must point to a file: {args.debug_picture}")
    return args.debug_picture


def validate_picture_type_options(
    debug_picture: Path | None,
    picture_type: str,
    crop_rect: CropRect | None,
    parser: argparse.ArgumentParser,
) -> None:
    actual_picture_type = resolve_picture_type(
        picture_type,
        crop_rect=crop_rect,
        debug_picture=debug_picture is not None,
    )

    if debug_picture is not None:
        if actual_picture_type == "raw" or crop_rect is None:
            return

        parser.error("--picture-type cropped/annotated/ocr_input cannot be combined with crop coordinates")

    if actual_picture_type in {"cropped", "annotated"} and crop_rect is None:
        parser.error("--picture-type cropped/annotated requires crop coordinates when capturing from camera")

    if actual_picture_type in {"raw", "ocr_input"}:
        return


def parse_debug_output(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path | None:
    if args.debug_output is None:
        return None
    if args.debug_output.exists() and not args.debug_output.is_dir():
        parser.error(f"--debug-output must be a directory path: {args.debug_output}")
    return args.debug_output


def parse_crop_output(args: argparse.Namespace, crop_rect: CropRect | None, parser: argparse.ArgumentParser) -> Path | None:
    if args.crop_output is None:
        return None
    if crop_rect is None:
        parser.error("--crop-output requires crop coordinates")
    return args.crop_output


def parse_camera_source(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CameraSource:
    if args.camera_source == "usb":
        if args.ip_camera_url is not None:
            parser.error("--ip-camera-url can only be used with --source ip")
        return CameraSource("usb", args.camera_index)

    if args.ip_camera_url is None:
        parser.error("--ip-camera-url is required when using --source ip")

    return CameraSource("ip", args.ip_camera_url)


def parse_postgres_target(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> PostgresTarget | None:
    if not args.pg_write:
        return None

    database_url = args.pg_database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("--pg-write requires --pg-database-url or the DATABASE_URL environment variable")
    if not args.pg_source.strip():
        parser.error("--pg-source must not be empty")

    return PostgresTarget(
        database_url=database_url,
        source=args.pg_source,
        value_mode=args.pg_value_mode,
    )


def open_camera(camera_source: CameraSource) -> cv2.VideoCapture:
    ensure_runtime_dependencies()
    camera = cv2.VideoCapture(camera_source.target)
    if camera_source.kind == "ip":
        camera.set(cv2.CAP_PROP_BUFFERSIZE, IP_CAMERA_BUFFER_SIZE)
    if camera.isOpened():
        return camera

    camera.release()
    raise RuntimeError(f"Could not open capture source {format_camera_source(camera_source)}")


def format_debug_paths(debug_paths: dict[str, Path]) -> str:
    return " ".join(f"{name}={path}" for name, path in sorted(debug_paths.items()))


def run_debug_picture(
    image_path: Path,
    pictures_root: Path,
    crop_rect: CropRect | None,
    debug_output_dir: Path | None,
    picture_type: str,
    ocr_preprocess: str,
    *,
    timestamp: datetime | None = None,
) -> int:
    ts = timestamp or datetime.now()
    saved_image_path = save_debug_picture_input(image_path, pictures_root, ts)
    actual_picture_type = resolve_picture_type(
        picture_type,
        crop_rect=crop_rect,
        debug_picture=True,
    )

    value = extract_value_from_image(
        saved_image_path,
        crop_rect=crop_rect,
        debug_output_dir=debug_output_dir,
        picture_type=actual_picture_type,
        ocr_preprocess=ocr_preprocess,
    )

    status = (
        f"debug_picture={image_path} picture_type={actual_picture_type} "
        f"ocr_preprocess={ocr_preprocess} saved={saved_image_path}"
    )
    if value is None:
        status += " value=<none>"
    else:
        status += f" value={value}"

    if debug_output_dir is not None:
        effective_crop_rect = crop_rect
        if actual_picture_type in {"cropped", "ocr_input"}:
            effective_crop_rect = None
        elif actual_picture_type == "annotated":
            image = read_image(saved_image_path)
            effective_crop_rect = find_crop_rect_in_annotated_image(image)

        debug_paths = build_debug_image_paths(saved_image_path, debug_output_dir, effective_crop_rect)
        status += f" {format_debug_paths(debug_paths)}"

    print(status)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    crop_rect = parse_crop_rect(args, parser)
    debug_picture = parse_debug_picture(args, parser)
    debug_output_dir = parse_debug_output(args, parser)
    crop_output_path = parse_crop_output(args, crop_rect, parser)
    validate_picture_type_options(debug_picture, args.picture_type, crop_rect, parser)
    postgres_target = parse_postgres_target(args, parser)

    if debug_picture is not None and postgres_target is not None:
        parser.error("--pg-write is only supported in live capture mode")
    if debug_picture is not None and crop_output_path is not None:
        parser.error("--crop-output is only supported in live capture mode")

    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be greater than 0")
    if args.persist_every <= 0:
        parser.error("--persist-every must be greater than 0")

    try:
        ensure_runtime_dependencies()
        if postgres_target is not None:
            ensure_postgres_dependencies()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    if debug_picture is not None:
        try:
            return run_debug_picture(
                debug_picture,
                args.pictures_dir,
                crop_rect,
                debug_output_dir,
                args.picture_type,
                args.ocr_preprocess,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"debug_error={exc}", file=sys.stderr)
            return 1

    camera_source = parse_camera_source(args, parser)

    camera: cv2.VideoCapture | None = None
    postgres_writer: PostgresWriter | None = None
    if camera_source.kind == "usb":
        try:
            camera = open_camera(camera_source)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1

    if postgres_target is not None:
        try:
            postgres_writer = PostgresWriter(postgres_target)
            postgres_writer.connect()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1

    print(
        "Starting capture loop "
        f"(source={format_camera_source(camera_source)}, interval={args.interval_seconds}s, "
        f"pictures_dir={args.pictures_dir}, csv={'disabled' if args.no_csv else args.csv_file}, crop={crop_rect}, "
        f"picture_type={args.picture_type}, ocr_preprocess={args.ocr_preprocess}, "
        f"persist_every={args.persist_every}, crop_output={crop_output_path}, "
        f"debug_output={debug_output_dir}, postgres={format_postgres_target(postgres_target) if postgres_target is not None else 'disabled'})"
    )

    capture_count = 0
    try:
        while True:
            try:
                persist_image = capture_count % args.persist_every == 0
                image_path, value, ts = run_capture_cycle(
                    camera,
                    args.pictures_dir,
                    args.csv_file,
                    camera_source=camera_source,
                    crop_rect=crop_rect,
                    picture_type=args.picture_type,
                    ocr_preprocess=args.ocr_preprocess,
                    debug_output_dir=debug_output_dir,
                    persist_image=persist_image,
                    write_csv=not args.no_csv,
                    crop_output_path=crop_output_path,
                    postgres_writer=postgres_writer,
                )
                capture_count += 1
                stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
                debug_suffix = ""
                if debug_output_dir is not None and image_path is not None:
                    effective_crop_rect = crop_rect
                    if resolve_picture_type(
                        args.picture_type,
                        crop_rect=crop_rect,
                        debug_picture=False,
                    ) == "cropped":
                        effective_crop_rect = None
                    debug_paths = build_debug_image_paths(image_path, debug_output_dir, effective_crop_rect)
                    debug_suffix = f" {format_debug_paths(debug_paths)}"
                saved_label = image_path if image_path is not None else "<skipped>"
                if value is None:
                    print(f"[{stamp}] saved={saved_label} value=<none>{debug_suffix}")
                else:
                    print(f"[{stamp}] saved={saved_label} value={value}{debug_suffix}")
            except Exception as exc:  # noqa: BLE001
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{stamp}] cycle_error={exc}", file=sys.stderr)

            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("Stopping capture loop.")
    finally:
        if camera is not None:
            camera.release()
        if postgres_writer is not None:
            postgres_writer.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
