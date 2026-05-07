from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import re
import threading
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import cv2
except ModuleNotFoundError as exc:
    cv2 = None
    _CV2_IMPORT_ERROR = exc
else:
    _CV2_IMPORT_ERROR = None

try:
    import psycopg
except ModuleNotFoundError as exc:
    psycopg = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None


METER_UNIT_PATTERN = re.compile(r"m\s*(?:\^?\s*3|³)", re.IGNORECASE)
NUMERIC_TOKEN_PATTERN = re.compile(r"\d(?:[\d\s.,]*\d)?")


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
class PostgresTarget:
    database_url: str
    source: str
    anomaly_threshold: int


@dataclass(frozen=True)
class ManualReadResult:
    recorded_at: datetime
    meter_value_m3: int
    image_path: Path
    crop_path: Path


HELP_EPILOG = """Examples:
  USB camera with crop coordinates:
    python3 app.py --camera-index 0 --x1 177 --y1 171 --x2 349 --y2 201

  USB camera with every 12th picture persisted:
    python3 app.py --x1 177 --y1 171 --x2 349 --y2 201 --interval 1 --persist-every 12

  USB camera with a fixed latest-crop output file:
    python3 app.py --x1 159 --y1 331 --x2 565 --y2 414 --crop-output meter-crop.png

  USB camera with PostgreSQL writes enabled:
    python3 app.py --interval 5 --x1 159 --y1 331 --x2 565 --y2 414 --pg-write

  Equivalent OCR request:
    curl http://localhost:11434/api/generate -d '{"model":"glm-ocr","prompt":"Text Recognition:","images":["<base64-image>"],"stream":false}'
"""


def find_project_python() -> Path | None:
    for path in (Path(".venv/bin/python"), Path("venv/bin/python")):
        if path.exists():
            return path
    return None


def ensure_runtime_dependencies() -> None:
    if _CV2_IMPORT_ERROR is None:
        return

    message = "Missing Python dependency: opencv-python."
    project_python = find_project_python()
    if project_python is not None:
        message += (
            f" Use `{project_python} app.py ...` or activate the virtualenv with "
            f"`source {project_python.parent / 'activate'}`."
        )
    message += " To install it into the current interpreter, run `python3 -m pip install -r requirements.txt`."
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
    if not text:
        return None

    sanitized = METER_UNIT_PATTERN.sub(" ", text)
    match = NUMERIC_TOKEN_PATTERN.search(sanitized)
    if not match:
        return None

    digits = re.sub(r"\D", "", match.group(0))
    return digits or None


def append_digit(value: int, digit: int | None) -> int:
    if digit is None:
        return value
    return value * 10 + digit


def get_ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def normalize_postgres_timestamp(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.astimezone().astimezone(timezone.utc)
    return timestamp.astimezone(timezone.utc)


def format_postgres_target(target: PostgresTarget | None) -> str:
    if target is None:
        return "disabled"
    return f"enabled(source={target.source})"


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
            raise RuntimeError(f"Could not connect to PostgreSQL: {exc}") from exc

    def _ensure_connection(self) -> Any:
        if self._connection is None or getattr(self._connection, "closed", False):
            self._connection = self._connect()
        return self._connection

    def connect(self) -> None:
        self._ensure_connection()

    def _fetch_previous_reading(self, cursor: Any, recorded_at: datetime) -> tuple[datetime, int] | None:
        cursor.execute(
            """
            SELECT recorded_at, meter_value_m3
            FROM (
                SELECT recorded_at, meter_value_m3, 1 AS source_priority
                FROM meter_readings
                WHERE recorded_at < %s

                UNION ALL

                SELECT recorded_at, meter_value_m3, 0 AS source_priority
                FROM meter_reading_anomalies
                WHERE recorded_at < %s
            ) AS previous_readings
            ORDER BY recorded_at DESC, source_priority DESC
            LIMIT 1
            """,
            (recorded_at, recorded_at),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        previous_recorded_at, previous_value = row
        return previous_recorded_at, int(previous_value)

    def _persist_anomaly(
        self,
        cursor: Any,
        *,
        recorded_at: datetime,
        value: int,
        previous_recorded_at: datetime,
        previous_value: int,
    ) -> None:
        delta = value - previous_value
        cursor.execute(
            """
            INSERT INTO meter_reading_anomalies (
                recorded_at,
                meter_value_m3,
                previous_recorded_at,
                previous_meter_value_m3,
                delta_m3,
                threshold_m3,
                source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recorded_at) DO UPDATE
            SET meter_value_m3 = EXCLUDED.meter_value_m3,
                previous_recorded_at = EXCLUDED.previous_recorded_at,
                previous_meter_value_m3 = EXCLUDED.previous_meter_value_m3,
                delta_m3 = EXCLUDED.delta_m3,
                threshold_m3 = EXCLUDED.threshold_m3,
                source = EXCLUDED.source
            """,
            (
                recorded_at,
                value,
                previous_recorded_at,
                previous_value,
                delta,
                self.target.anomaly_threshold,
                self.target.source,
            ),
        )

    def persist(self, timestamp: datetime, value: int) -> None:
        recorded_at = normalize_postgres_timestamp(timestamp)
        connection = self._ensure_connection()

        try:
            with connection.cursor() as cursor:
                previous = self._fetch_previous_reading(cursor, recorded_at)
                if previous is not None:
                    previous_recorded_at, previous_value = previous
                    if value - previous_value > self.target.anomaly_threshold:
                        self._persist_anomaly(
                            cursor,
                            recorded_at=recorded_at,
                            value=value,
                            previous_recorded_at=previous_recorded_at,
                            previous_value=previous_value,
                        )
                        return

                cursor.execute(
                    """
                    INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (recorded_at) DO UPDATE
                    SET meter_value_m3 = EXCLUDED.meter_value_m3,
                        source = EXCLUDED.source
                    """,
                    (recorded_at, value, self.target.source),
                )
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RuntimeError(f"Failed to persist reading to PostgreSQL: {exc}") from exc


def build_capture_image_path(pictures_root: Path, timestamp: datetime) -> Path:
    day_dir = pictures_root / timestamp.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"


def build_processed_image_path(pictures_root: Path, timestamp: datetime) -> Path:
    day_dir = pictures_root / timestamp.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"


def write_image(image_path: Path, image: cv2.typing.MatLike) -> None:
    ensure_runtime_dependencies()
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(image_path), image):
        raise RuntimeError(f"Failed to write image to {image_path}")


def read_frame(camera: cv2.VideoCapture) -> cv2.typing.MatLike:
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


def write_crop_output(crop_output_path: Path, cropped: cv2.typing.MatLike) -> None:
    crop_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_image(crop_output_path, cropped)


def write_processed_image(
    pictures_root: Path,
    timestamp: datetime,
    cropped: cv2.typing.MatLike,
) -> Path:
    image_path = build_processed_image_path(pictures_root, timestamp)
    write_image(image_path, cropped)
    return image_path


def run_ollama_ocr(crop_output_path: Path) -> int:
    base_url = get_ollama_base_url()
    image_base64 = base64.b64encode(crop_output_path.read_bytes()).decode("ascii")
    payload = json.dumps(
        {
            "model": "glm-ocr",
            "prompt": "Text Recognition:",
            "images": [image_base64],
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Ollama OCR failed: {details or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama API at {base_url}: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama OCR returned invalid JSON") from exc

    normalized = normalize_ocr_text(str(data.get("response", "")))
    if normalized is None:
        raise RuntimeError("No numeric meter reading found in Ollama OCR output")

    return int(normalized)


def capture_and_save_image(
    camera: cv2.VideoCapture,
    pictures_root: Path,
    timestamp: datetime,
    *,
    crop_rect: CropRect | None = None,
    persist_image: bool = True,
) -> tuple[Path | None, cv2.typing.MatLike, cv2.typing.MatLike]:
    frame = read_frame(camera)
    cropped = crop_image(frame, crop_rect)

    image_path: Path | None = None
    if persist_image:
        image_path = build_capture_image_path(pictures_root, timestamp)
        write_image(image_path, frame)

    return image_path, frame, cropped


def run_capture_cycle(
    camera: cv2.VideoCapture,
    pictures_root: Path,
    *,
    timestamp: datetime | None = None,
    crop_rect: CropRect | None = None,
    persist_image: bool = True,
    crop_output_path: Path | None = None,
    processed_pictures_root: Path | None = None,
    postgres_writer: PostgresWriter | None = None,
    ocr_append_digit: int | None = None,
    ocr_func=run_ollama_ocr,
) -> tuple[Path | None, int, datetime]:
    ensure_runtime_dependencies()
    ts = timestamp or datetime.now()
    image_path, _image, cropped = capture_and_save_image(
        camera,
        pictures_root,
        ts,
        crop_rect=crop_rect,
        persist_image=persist_image,
    )

    effective_crop_output_path = crop_output_path or Path("meter-crop.png")
    write_crop_output(effective_crop_output_path, cropped)
    if persist_image and processed_pictures_root is not None:
        write_processed_image(processed_pictures_root, ts, cropped)

    value = append_digit(ocr_func(effective_crop_output_path), ocr_append_digit)
    if postgres_writer is not None:
        postgres_writer.persist(ts, value)

    return image_path, value, ts


def run_manual_read(
    camera: cv2.VideoCapture,
    pictures_root: Path,
    *,
    crop_rect: CropRect,
    crop_output_path: Path,
    processed_pictures_root: Path,
    postgres_writer: PostgresWriter | None = None,
    ocr_append_digit: int | None = None,
    capture_lock: threading.Lock | None = None,
) -> ManualReadResult:
    lock_context = capture_lock if capture_lock is not None else contextlib.nullcontext()
    with lock_context:
        image_path, value, ts = run_capture_cycle(
            camera,
            pictures_root,
            timestamp=None,
            crop_rect=crop_rect,
            persist_image=True,
            crop_output_path=crop_output_path,
            processed_pictures_root=processed_pictures_root,
            postgres_writer=postgres_writer,
            **({"ocr_append_digit": ocr_append_digit} if ocr_append_digit is not None else {}),
        )

    if image_path is None:
        raise RuntimeError("Manual read did not persist the original image")

    crop_path = processed_pictures_root / ts.strftime("%Y-%m-%d") / f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
    return ManualReadResult(
        recorded_at=ts,
        meter_value_m3=value,
        image_path=image_path,
        crop_path=crop_path,
    )


def format_api_timestamp(timestamp: datetime) -> str:
    return normalize_postgres_timestamp(timestamp).isoformat().replace("+00:00", "Z")


def manual_read_payload(result: ManualReadResult) -> dict[str, object]:
    return {
        "recorded_at": format_api_timestamp(result.recorded_at),
        "meter_value_m3": result.meter_value_m3,
        "image_path": result.image_path.as_posix(),
        "crop_path": result.crop_path.as_posix(),
    }


def parse_control_bind(value: str | None, parser: argparse.ArgumentParser) -> tuple[str, int] | None:
    if value is None:
        return None

    bind = value.strip()
    if not bind:
        parser.error("--control-bind must not be empty")

    host, separator, port_text = bind.rpartition(":")
    if not separator or not host or not port_text:
        parser.error("--control-bind must use HOST:PORT")

    try:
        port = int(port_text)
    except ValueError as exc:
        parser.error(f"invalid control port: {exc}")

    if port <= 0 or port > 65535:
        parser.error("--control-bind port must be between 1 and 65535")

    return host, port


def start_control_server(
    bind_address: tuple[str, int],
    trigger_manual_read,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    class ReaderControlHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/manual-read":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            try:
                result = trigger_manual_read()
            except Exception as exc:  # noqa: BLE001
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            self._write_json(HTTPStatus.OK, manual_read_payload(result))

        def log_message(self, format: str, *args: object) -> None:
            return None

        def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(bind_address, ReaderControlHandler)
    thread = threading.Thread(target=server.serve_forever, name="reader-control", daemon=True)
    thread.start()
    return server, thread


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture images from a USB camera, crop a rectangle, OCR it with Ollama, and optionally store the reading in PostgreSQL.",
        formatter_class=AppHelpFormatter,
        epilog=HELP_EPILOG,
    )

    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV camera index for the USB camera.",
    )
    parser.add_argument(
        "--interval-seconds",
        "--interval",
        dest="interval_seconds",
        type=float,
        default=30,
        help="Seconds to wait between capture cycles.",
    )
    parser.add_argument(
        "--pictures-dir",
        type=Path,
        default=Path("pictures"),
        help="Root directory where original captured pictures are stored.",
    )
    parser.add_argument(
        "--processed-pictures-dir",
        type=Path,
        default=Path("processed"),
        help="Root directory where processed crop pictures are archived when the original capture is persisted.",
    )
    parser.add_argument(
        "--persist-every",
        type=int,
        default=1,
        help=(
            "Persist the original captured picture every N cycles. "
            "The first live capture is always persisted."
        ),
    )
    parser.add_argument(
        "--crop-output",
        type=Path,
        default=Path("meter-crop.png"),
        help="Fixed file path where the current cropped rectangle is written on each capture cycle.",
    )
    parser.add_argument(
        "--ocr-append-digit",
        type=int,
        choices=range(10),
        default=None,
        help="Append one trailing digit to the OCR reading before logging and storing it. Leave unset to keep the OCR value unchanged.",
    )
    parser.add_argument(
        "--manual-read",
        action="store_true",
        help="Run exactly one capture cycle immediately, always persisting both original and processed images.",
    )
    parser.add_argument(
        "--control-bind",
        help="Expose a local HTTP control endpoint on HOST:PORT with POST /manual-read.",
    )

    parser.add_argument("--x1", type=int, help="Left X coordinate of the crop rectangle.")
    parser.add_argument("--y1", type=int, help="Top Y coordinate of the crop rectangle.")
    parser.add_argument("--x2", type=int, help="Right X coordinate of the crop rectangle.")
    parser.add_argument("--y2", type=int, help="Bottom Y coordinate of the crop rectangle.")

    parser.add_argument(
        "--pg-write",
        action="store_true",
        help="Insert the meter reading recognized by Ollama OCR into the Water Meter PostgreSQL table `meter_readings`.",
    )
    parser.add_argument(
        "--pg-database-url",
        help="PostgreSQL connection string. Defaults to the `DATABASE_URL` environment variable when set.",
    )
    parser.add_argument(
        "--pg-source",
        default="reader",
        help="Value written into the `source` column for PostgreSQL inserts.",
    )
    parser.add_argument(
        "--pg-anomaly-threshold",
        type=int,
        default=100,
        help="Skip inserts when the reading jumps above the previous value by more than this amount, and log them as anomalies.",
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


def parse_crop_output(args: argparse.Namespace, crop_rect: CropRect | None, parser: argparse.ArgumentParser) -> Path | None:
    if crop_rect is None:
        parser.error("--crop-output requires crop coordinates")
    return args.crop_output


def parse_postgres_target(args: argparse.Namespace, parser: argparse.ArgumentParser) -> PostgresTarget | None:
    if not args.pg_write:
        return None

    database_url = args.pg_database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("--pg-write requires --pg-database-url or the DATABASE_URL environment variable")
    if not args.pg_source.strip():
        parser.error("--pg-source must not be empty")
    if args.pg_anomaly_threshold < 0:
        parser.error("--pg-anomaly-threshold must be greater than or equal to 0")

    return PostgresTarget(
        database_url=database_url,
        source=args.pg_source,
        anomaly_threshold=args.pg_anomaly_threshold,
    )


def open_camera(camera_index: int) -> cv2.VideoCapture:
    ensure_runtime_dependencies()
    camera = cv2.VideoCapture(camera_index)
    if camera.isOpened():
        return camera

    camera.release()
    raise RuntimeError(f"Could not open USB camera index {camera_index}")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    crop_rect = parse_crop_rect(args, parser)
    if crop_rect is None:
        parser.error("Crop coordinates are required: provide --x1, --y1, --x2, and --y2")
    crop_output_path = parse_crop_output(args, crop_rect, parser)
    postgres_target = parse_postgres_target(args, parser)
    control_bind = parse_control_bind(args.control_bind, parser)

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

    try:
        camera = open_camera(args.camera_index)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    postgres_writer: PostgresWriter | None = None
    if postgres_target is not None:
        try:
            postgres_writer = PostgresWriter(postgres_target)
            postgres_writer.connect()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            camera.release()
            return 1

    capture_lock = threading.Lock()

    def trigger_manual_read() -> ManualReadResult:
        return run_manual_read(
            camera,
            args.pictures_dir,
            crop_rect=crop_rect,
            crop_output_path=crop_output_path,
            processed_pictures_root=args.processed_pictures_dir,
            postgres_writer=postgres_writer,
            ocr_append_digit=args.ocr_append_digit,
            capture_lock=capture_lock,
        )

    control_server: ThreadingHTTPServer | None = None
    control_thread: threading.Thread | None = None

    print(
        "Starting capture loop "
        f"(source=usb(index={args.camera_index}), interval={args.interval_seconds}s, "
        f"pictures_dir={args.pictures_dir}, crop={crop_rect}, persist_every={args.persist_every}, "
        f"crop_output={crop_output_path}, ocr=ollama(glm-ocr), postgres={format_postgres_target(postgres_target)})"
    )

    capture_count = 0
    try:
        if args.manual_read:
            result = trigger_manual_read()
            stamp = result.recorded_at.strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{stamp}] manual read complete saved={result.image_path} "
                f"crop={result.crop_path} value={result.meter_value_m3}"
            )
            return 0

        if control_bind is not None:
            control_server, control_thread = start_control_server(control_bind, trigger_manual_read)
            print(f"Reader control API listening on http://{control_bind[0]}:{control_bind[1]}/manual-read")

        while True:
            try:
                persist_image = capture_count % args.persist_every == 0
                with capture_lock:
                    image_path, value, ts = run_capture_cycle(
                        camera,
                        args.pictures_dir,
                        timestamp=None,
                        crop_rect=crop_rect,
                        persist_image=persist_image,
                        crop_output_path=crop_output_path,
                        processed_pictures_root=args.processed_pictures_dir,
                        postgres_writer=postgres_writer,
                        **(
                            {"ocr_append_digit": args.ocr_append_digit}
                            if args.ocr_append_digit is not None
                            else {}
                        ),
                    )
                capture_count += 1
                stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
                saved_label = image_path if image_path is not None else "<skipped>"
                print(f"[{stamp}] saved={saved_label} value={value}")
            except Exception as exc:  # noqa: BLE001
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{stamp}] cycle_error={exc}", file=sys.stderr)

            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("Stopping capture loop.")
    finally:
        if control_server is not None:
            control_server.shutdown()
            control_server.server_close()
        if control_thread is not None:
            control_thread.join(timeout=5)
        camera.release()
        if postgres_writer is not None:
            postgres_writer.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
