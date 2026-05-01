from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from app import (
    CameraSource,
    CropRect,
    PostgresWriter,
    PostgresTarget,
    add_ocr_border,
    build_arg_parser,
    convert_ocr_value_to_meter_value,
    crop_image,
    normalize_ocr_text,
    parse_camera_source,
    parse_crop_output,
    parse_crop_rect,
    parse_postgres_target,
    prepare_image_for_ocr,
    run_capture_cycle,
)


class FakeCamera:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()


def read_csv(path: Path) -> list[list[str]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.reader(file))


def test_normalize_ocr_text() -> None:
    assert normalize_ocr_text("12345") == "12345"
    assert normalize_ocr_text("meter: 12,34 l") == "12.34"
    assert normalize_ocr_text("abc") is None
    assert normalize_ocr_text("") is None


def test_convert_ocr_value_to_meter_value_modes() -> None:
    assert convert_ocr_value_to_meter_value("12345", "truncate") == 12345
    assert convert_ocr_value_to_meter_value("12345.99", "truncate") == 12345
    assert convert_ocr_value_to_meter_value("12345.50", "round") == 12346
    assert convert_ocr_value_to_meter_value("12345", "reject") == 12345


def test_convert_ocr_value_to_meter_value_rejects_fraction_when_requested() -> None:
    with pytest.raises(ValueError, match="fractional component"):
        convert_ocr_value_to_meter_value("12345.67", "reject")


def test_postgres_writer_persists_upsert_query(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, object] = {}

    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            executed["query"] = query
            executed["params"] = params

    class FakeConnection:
        closed = False

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = True

    fake_connection = FakeConnection()

    def fake_connect(database_url: str, autocommit: bool) -> FakeConnection:
        executed["database_url"] = database_url
        executed["autocommit"] = autocommit
        return fake_connection

    monkeypatch.setattr(app, "_PSYCOPG_IMPORT_ERROR", None)
    monkeypatch.setattr(app, "psycopg", SimpleNamespace(connect=fake_connect))

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
            value_mode="truncate",
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 20, 30), "321.9")

    assert executed["database_url"] == "postgres://meter:meter@db:5432/water_meter"
    assert executed["autocommit"] is True
    assert "INSERT INTO meter_readings" in str(executed["query"])
    assert "ON CONFLICT (recorded_at) DO UPDATE" in str(executed["query"])
    params = executed["params"]
    assert isinstance(params, tuple)
    assert params[1:] == (321, "reader-test")
    assert getattr(params[0], "tzinfo", None) is not None


def test_run_capture_cycle_writes_image_and_csv(tmp_path: Path) -> None:
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 30)

    pictures_dir = tmp_path / "pictures"
    csv_file = tmp_path / "readings.csv"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        csv_file,
        timestamp=timestamp,
        ocr_func=lambda _: "123.4",
    )

    assert value == "123.4"
    assert ts == timestamp
    assert image_path == pictures_dir / "2026-03-16" / "2026-03-16_10-20-30.jpg"
    assert image_path.exists()

    rows = read_csv(csv_file)
    assert rows == [
        ["date time", "value"],
        ["2026-03-16 10:20:30", "123.4"],
    ]


def test_run_capture_cycle_persists_to_postgres_writer(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 45)
    calls: list[tuple[datetime, str | None]] = []

    class FakePostgresWriter:
        def persist(self, ts: datetime, value: str | None) -> None:
            calls.append((ts, value))

    _, value, ts = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        tmp_path / "readings.csv",
        timestamp=timestamp,
        postgres_writer=FakePostgresWriter(),
        ocr_func=lambda _: "321.9",
    )

    assert value == "321.9"
    assert ts == timestamp
    assert calls == [(timestamp, "321.9")]


def test_run_capture_cycle_writes_fixed_crop_output(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 50)
    crop_rect = CropRect(8, 4, 22, 16)
    crop_output = tmp_path / "meter-crop.png"

    run_capture_cycle(
        camera,
        tmp_path / "pictures",
        tmp_path / "readings.csv",
        timestamp=timestamp,
        crop_rect=crop_rect,
        crop_output_path=crop_output,
        ocr_func=lambda _: "123.0",
    )

    saved = cv2.imread(str(crop_output))
    assert saved is not None
    np.testing.assert_array_equal(saved, crop_image(frame, crop_rect))


def test_run_capture_cycle_with_crop_rect_saves_prepared_ocr_image(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 21, 0)

    pictures_dir = tmp_path / "pictures"
    csv_file = tmp_path / "readings.csv"
    crop_rect = CropRect(8, 4, 22, 16)
    captured: dict[str, np.ndarray] = {}

    def fake_ocr(prepared: np.ndarray) -> str:
        captured["prepared"] = prepared.copy()
        return "816.01"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        csv_file,
        timestamp=timestamp,
        crop_rect=crop_rect,
        ocr_func=fake_ocr,
    )

    expected = prepare_image_for_ocr(crop_image(frame, crop_rect))
    saved = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)

    assert value == "816.01"
    assert ts == timestamp
    assert image_path == pictures_dir / "2026-03-16" / "2026-03-16_10-21-00.png"
    assert image_path.exists()
    assert saved is not None
    np.testing.assert_array_equal(saved, expected)
    np.testing.assert_array_equal(captured["prepared"], expected)

    rows = read_csv(csv_file)
    assert rows == [
        ["date time", "value"],
        ["2026-03-16 10:21:00", "816.01"],
    ]


def test_run_capture_cycle_with_picture_type_cropped_saves_cropped_image(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 21, 30)

    pictures_dir = tmp_path / "pictures"
    csv_file = tmp_path / "readings.csv"
    crop_rect = CropRect(8, 4, 22, 16)
    captured: dict[str, np.ndarray] = {}

    def fake_ocr(prepared: np.ndarray) -> str:
        captured["prepared"] = prepared.copy()
        return "816.02"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        csv_file,
        timestamp=timestamp,
        crop_rect=crop_rect,
        picture_type="cropped",
        ocr_func=fake_ocr,
    )

    expected_cropped = crop_image(frame, crop_rect)
    expected_prepared = prepare_image_for_ocr(expected_cropped)
    saved = cv2.imread(str(image_path))

    assert value == "816.02"
    assert ts == timestamp
    assert image_path == pictures_dir / "2026-03-16" / "2026-03-16_10-21-30.png"
    assert saved is not None
    np.testing.assert_array_equal(saved, expected_cropped)
    np.testing.assert_array_equal(captured["prepared"], expected_prepared)


def test_run_capture_cycle_without_persistence_still_ocrs_and_writes_csv(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 22, 0)

    pictures_dir = tmp_path / "pictures"
    csv_file = tmp_path / "readings.csv"
    crop_rect = CropRect(8, 4, 22, 16)
    debug_dir = tmp_path / "debug"
    captured: dict[str, np.ndarray] = {}

    def fake_ocr(prepared: np.ndarray) -> str:
        captured["prepared"] = prepared.copy()
        return "816.03"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        csv_file,
        timestamp=timestamp,
        crop_rect=crop_rect,
        debug_output_dir=debug_dir,
        persist_image=False,
        ocr_func=fake_ocr,
    )

    expected = prepare_image_for_ocr(crop_image(frame, crop_rect))

    assert image_path is None
    assert value == "816.03"
    assert ts == timestamp
    np.testing.assert_array_equal(captured["prepared"], expected)
    assert not pictures_dir.exists()
    assert not debug_dir.exists()

    rows = read_csv(csv_file)
    assert rows == [
        ["date time", "value"],
        ["2026-03-16 10:22:00", "816.03"],
    ]


def test_run_capture_cycle_ip_source_opens_temporary_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = np.full((20, 30, 3), 200, dtype=np.uint8)
    timestamp = datetime(2026, 3, 30, 19, 15, 0)
    pictures_dir = tmp_path / "pictures"
    csv_file = tmp_path / "readings.csv"
    source = CameraSource("ip", "rtsp://camera/stream1")
    capture_calls: dict[str, object] = {}

    class FakeIpCamera:
        def __init__(self, image: np.ndarray) -> None:
            self._image = image
            self.grab_calls = 0
            self.released = False

        def grab(self) -> bool:
            self.grab_calls += 1
            return True

        def read(self) -> tuple[bool, np.ndarray]:
            return True, self._image.copy()

        def release(self) -> None:
            self.released = True

    fake_camera = FakeIpCamera(frame)

    def fake_open_camera(camera_source: CameraSource) -> FakeIpCamera:
        capture_calls["camera_source"] = camera_source
        return fake_camera

    monkeypatch.setattr(app, "open_camera", fake_open_camera)

    image_path, value, ts = run_capture_cycle(
        None,
        pictures_dir,
        csv_file,
        timestamp=timestamp,
        camera_source=source,
        picture_type="ocr_input",
        ocr_func=lambda _: "222.0",
    )

    assert ts == timestamp
    assert value == "222.0"
    assert capture_calls["camera_source"] == source
    assert fake_camera.grab_calls == app.IP_CAMERA_FLUSH_GRABS
    assert fake_camera.released is True
    assert image_path == pictures_dir / "2026-03-30" / "2026-03-30_19-15-00.png"
    assert image_path.exists()


def test_run_capture_cycle_ocr_failure_writes_empty_value(tmp_path: Path) -> None:
    frame = np.zeros((32, 64, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 11, 0, 0)

    csv_file = tmp_path / "readings.csv"

    _, value, _ = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        csv_file,
        timestamp=timestamp,
        ocr_func=lambda _: None,
    )

    assert value is None
    rows = read_csv(csv_file)
    assert rows == [
        ["date time", "value"],
        ["2026-03-16 11:00:00", ""],
    ]


def test_crop_image_uses_requested_rectangle() -> None:
    image = np.arange(6 * 8 * 3, dtype=np.uint8).reshape((6, 8, 3))

    cropped = crop_image(image, CropRect(2, 1, 6, 4))

    assert cropped.shape == (3, 4, 3)
    np.testing.assert_array_equal(cropped, image[1:4, 2:6])


def test_find_crop_rect_in_annotated_image_detects_saved_rectangle() -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    crop_rect = CropRect(8, 4, 22, 16)

    annotated = app.annotate_image(image, crop_rect)

    assert app.find_crop_rect_in_annotated_image(annotated) == crop_rect


def test_parse_crop_rect_accepts_complete_rectangle() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--x1", "10", "--y1", "20", "--x2", "30", "--y2", "40"])

    crop_rect = parse_crop_rect(args, parser)

    assert crop_rect == CropRect(10, 20, 30, 40)


def test_interval_alias_sets_interval_seconds() -> None:
    parser = build_arg_parser()

    args = parser.parse_args(["--interval", "3"])

    assert args.interval_seconds == 3


def test_persist_every_argument_is_parsed() -> None:
    parser = build_arg_parser()

    args = parser.parse_args(["--persist-every", "12"])

    assert args.persist_every == 12


def test_parse_camera_source_defaults_to_usb() -> None:
    parser = build_arg_parser()

    args = parser.parse_args([])

    assert parse_camera_source(args, parser) == CameraSource("usb", 0)


def test_parse_camera_source_accepts_ip_camera_url() -> None:
    parser = build_arg_parser()
    url = "rtsp://admin:secret@192.168.10.31:554/stream1"

    args = parser.parse_args(["--source", "ip", "--ip-camera-url", url])

    assert parse_camera_source(args, parser) == CameraSource("ip", url)


def test_parse_camera_source_requires_ip_camera_url_for_ip_source() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--source", "ip"])

    with pytest.raises(SystemExit):
        parse_camera_source(args, parser)


def test_parse_camera_source_rejects_ip_camera_url_for_usb_source() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--source", "usb", "--ip-camera-url", "rtsp://camera/stream1"])

    with pytest.raises(SystemExit):
        parse_camera_source(args, parser)


def test_parse_postgres_target_defaults_to_disabled() -> None:
    parser = build_arg_parser()
    args = parser.parse_args([])

    assert parse_postgres_target(args, parser) is None


def test_parse_postgres_target_uses_explicit_database_url() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--pg-write",
            "--pg-database-url",
            "postgres://meter:meter@localhost:5432/water_meter",
            "--pg-source",
            "camera-reader",
            "--pg-value-mode",
            "round",
        ]
    )

    assert parse_postgres_target(args, parser) == PostgresTarget(
        database_url="postgres://meter:meter@localhost:5432/water_meter",
        source="camera-reader",
        value_mode="round",
    )


def test_parse_postgres_target_uses_database_url_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--pg-write"])
    monkeypatch.setenv("DATABASE_URL", "postgres://meter:meter@db:5432/water_meter")

    assert parse_postgres_target(args, parser) == PostgresTarget(
        database_url="postgres://meter:meter@db:5432/water_meter",
        source="reader",
        value_mode="truncate",
    )


def test_parse_postgres_target_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--pg-write"])
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit):
        parse_postgres_target(args, parser)


def test_parse_crop_output_defaults_to_disabled() -> None:
    parser = build_arg_parser()
    args = parser.parse_args([])

    assert parse_crop_output(args, None, parser) is None


def test_parse_crop_output_requires_crop_rect() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--crop-output", "meter-crop.png"])

    with pytest.raises(SystemExit):
        parse_crop_output(args, None, parser)


def test_parse_crop_rect_rejects_partial_rectangle() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--x1", "10", "--y1", "20"])

    with pytest.raises(SystemExit):
        parse_crop_rect(args, parser)


def test_add_ocr_border_adds_small_padding() -> None:
    image = np.zeros((30, 100), dtype=np.uint8)

    bordered = add_ocr_border(image)

    assert bordered.shape == (30, 112)


def test_prepare_image_for_ocr_preserves_white_digits_on_red_background() -> None:
    image = np.full((24, 48, 3), 255, dtype=np.uint8)

    image[4:20, 4:18] = 0
    image[7:17, 10:13] = (255, 255, 255)
    image[7:10, 8:16] = (255, 255, 255)
    image[14:17, 8:16] = (255, 255, 255)

    image[4:20, 24:42] = (0, 0, 220)
    image[7:17, 30:33] = (255, 255, 255)
    image[7:10, 28:36] = (255, 255, 255)
    image[14:17, 28:36] = (255, 255, 255)

    prepared = prepare_image_for_ocr(image)

    black_region = prepared[12:60, 12:54]
    red_region = prepared[12:60, 72:126]
    assert black_region.min() == 0
    assert black_region.max() == 255
    assert red_region.min() == 0
    assert red_region.max() == 255


def test_extract_value_from_image_writes_debug_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    image[4:16, 8:22] = (0, 0, 255)
    image_path = tmp_path / "meter.png"
    assert cv2.imwrite(str(image_path), image)

    debug_dir = tmp_path / "debug"
    crop_rect = CropRect(8, 4, 22, 16)

    monkeypatch.setattr(app.pytesseract, "image_to_string", lambda _image, config: "00816.01")

    value = app.extract_value_from_image(
        image_path,
        crop_rect=crop_rect,
        debug_output_dir=debug_dir,
    )

    assert value == "00816.01"

    debug_paths = app.build_debug_image_paths(image_path, debug_dir, crop_rect)
    for path in debug_paths.values():
        assert path.exists()

    cropped = cv2.imread(str(debug_paths["cropped"]))
    assert cropped.shape[:2] == (12, 14)

    prepared = cv2.imread(str(debug_paths["ocr_input"]), cv2.IMREAD_GRAYSCALE)
    assert prepared.shape == (36, 66)


def test_extract_value_from_annotated_image_uses_detected_rectangle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    image[4:16, 8:22] = (0, 0, 255)
    crop_rect = CropRect(8, 4, 22, 16)
    image_path = tmp_path / "meter_annotated.png"
    annotated = app.annotate_image(image, crop_rect)
    assert cv2.imwrite(str(image_path), annotated)

    debug_dir = tmp_path / "debug"

    monkeypatch.setattr(app.pytesseract, "image_to_string", lambda _image, config: "00816.01")

    value = app.extract_value_from_image(
        image_path,
        debug_output_dir=debug_dir,
        picture_type="annotated",
    )

    assert value == "00816.01"

    debug_paths = app.build_debug_image_paths(image_path, debug_dir, crop_rect)
    for path in debug_paths.values():
        assert path.exists()

    cropped = cv2.imread(str(debug_paths["cropped"]))
    assert cropped.shape[:2] == (12, 14)

    prepared = cv2.imread(str(debug_paths["ocr_input"]), cv2.IMREAD_GRAYSCALE)
    assert prepared.shape == (36, 66)


def test_run_debug_picture_saves_exact_input_file_to_pictures_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_path = tmp_path / "meter_annotated.png"
    image = np.zeros((12, 18, 3), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)

    pictures_dir = tmp_path / "pictures"
    timestamp = datetime(2026, 3, 27, 15, 30, 45)

    calls: dict[str, object] = {}

    def fake_extract(
        path: Path,
        crop_rect: CropRect | None = None,
        debug_output_dir: Path | None = None,
        picture_type: str = "raw",
    ) -> str:
        calls["path"] = path
        calls["crop_rect"] = crop_rect
        calls["debug_output_dir"] = debug_output_dir
        calls["picture_type"] = picture_type
        return "91.7"

    monkeypatch.setattr(app, "extract_value_from_image", fake_extract)

    exit_code = app.run_debug_picture(
        image_path,
        pictures_dir,
        None,
        None,
        "annotated",
        timestamp=timestamp,
    )

    assert exit_code == 0
    saved_path = pictures_dir / "2026-03-27" / "2026-03-27_15-30-45.png"
    assert calls == {
        "path": saved_path,
        "crop_rect": None,
        "debug_output_dir": None,
        "picture_type": "annotated",
    }

    assert saved_path.exists()
    assert saved_path.read_bytes() == image_path.read_bytes()

    out = capsys.readouterr().out
    assert f"saved={saved_path}" in out
    assert "value=91.7" in out


def test_main_debug_picture_processes_existing_file_without_camera(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_path = tmp_path / "meter.png"
    assert cv2.imwrite(str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))

    calls: dict[str, object] = {}

    def fake_extract(
        path: Path,
        crop_rect: CropRect | None = None,
        debug_output_dir: Path | None = None,
        picture_type: str = "raw",
    ) -> str:
        calls["path"] = path
        calls["crop_rect"] = crop_rect
        calls["debug_output_dir"] = debug_output_dir
        calls["picture_type"] = picture_type
        return "88.1"

    monkeypatch.setattr(app, "extract_value_from_image", fake_extract)
    monkeypatch.setattr(
        app.cv2,
        "VideoCapture",
        lambda _index: (_ for _ in ()).throw(AssertionError("camera should not be opened")),
    )

    class FrozenDatetime:
        @classmethod
        def now(cls) -> datetime:
            return datetime(2026, 3, 27, 16, 0, 0)

    monkeypatch.setattr(app, "datetime", FrozenDatetime)

    pictures_dir = tmp_path / "pictures"

    exit_code = app.main(
        [
            "--debug-picture",
            str(image_path),
            "--pictures-dir",
            str(pictures_dir),
            "--x1",
            "1",
            "--y1",
            "2",
            "--x2",
            "8",
            "--y2",
            "9",
        ]
    )

    assert exit_code == 0
    saved_path = pictures_dir / "2026-03-27" / "2026-03-27_16-00-00.png"
    assert calls == {
        "path": saved_path,
        "crop_rect": CropRect(1, 2, 8, 9),
        "debug_output_dir": None,
        "picture_type": "raw",
    }

    out = capsys.readouterr().out
    assert f"debug_picture={image_path}" in out
    assert "picture_type=raw" in out
    assert f"saved={saved_path}" in out
    assert "value=88.1" in out
    assert saved_path.exists()


def test_main_rejects_crop_coordinates_for_annotated_debug_picture(tmp_path: Path) -> None:
    image_path = tmp_path / "meter.png"
    assert cv2.imwrite(str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))

    with pytest.raises(SystemExit):
        app.main(
            [
                "--debug-picture",
                str(image_path),
                "--picture-type",
                "annotated",
                "--x1",
                "1",
                "--y1",
                "2",
                "--x2",
                "8",
                "--y2",
                "9",
            ]
        )


def test_main_rejects_pg_write_with_debug_picture(tmp_path: Path) -> None:
    image_path = tmp_path / "meter.png"
    assert cv2.imwrite(str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))

    with pytest.raises(SystemExit):
        app.main(
            [
                "--debug-picture",
                str(image_path),
                "--pg-write",
                "--pg-database-url",
                "postgres://meter:meter@db:5432/water_meter",
            ]
        )


def test_main_rejects_crop_output_with_debug_picture(tmp_path: Path) -> None:
    image_path = tmp_path / "meter.png"
    assert cv2.imwrite(str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))

    with pytest.raises(SystemExit):
        app.main(
            [
                "--debug-picture",
                str(image_path),
                "--x1",
                "1",
                "--y1",
                "2",
                "--x2",
                "8",
                "--y2",
                "9",
                "--crop-output",
                "meter-crop.png",
            ]
        )


def test_main_rejects_non_positive_persist_every() -> None:
    with pytest.raises(SystemExit):
        app.main(["--persist-every", "0"])


def test_main_reports_missing_python_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "_PYTESSERACT_IMPORT_ERROR", ModuleNotFoundError("No module named 'pytesseract'"))
    monkeypatch.setattr(app, "find_project_python", lambda: Path(".venv/bin/python"))

    exit_code = app.main(["--interval", "3"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Missing Python dependencies: pytesseract." in err
    assert "python3 -m pip install -r requirements.txt" in err
    assert ".venv/bin/python app.py ..." in err


def test_extract_value_from_prepared_image_reports_missing_tesseract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.pytesseract,
        "image_to_string",
        lambda _image, config: (_ for _ in ()).throw(app.pytesseract.TesseractNotFoundError()),
    )

    with pytest.raises(RuntimeError, match="tesseract"):
        app.extract_value_from_prepared_image(np.zeros((10, 10), dtype=np.uint8))


def test_help_text_includes_ip_camera_usage_examples() -> None:
    help_text = build_arg_parser().format_help()

    assert "--source {usb,ip}" in help_text
    assert "--ip-camera-url IP_CAMERA_URL" in help_text
    assert "--persist-every PERSIST_EVERY" in help_text
    assert "--crop-output CROP_OUTPUT" in help_text
    assert "--pg-write" in help_text
    assert "python3 app.py --source ip --ip-camera-url" in help_text
    assert "python3 app.py --debug-picture" in help_text


def test_main_uses_ip_camera_source_and_masks_password_in_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream_url = "rtsp://admin:super-secret@192.168.10.31:554/stream1"
    capture_calls: dict[str, object] = {}

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        csv_path: Path,
        *,
        timestamp: datetime | None = None,
        camera_source: CameraSource | None = None,
        crop_rect: CropRect | None = None,
        picture_type: str = "auto",
        debug_output_dir: Path | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        postgres_writer: object | None = None,
        ocr_func=app.extract_value_from_prepared_image,
    ) -> tuple[Path | None, str | None, datetime]:
        capture_calls["camera"] = camera
        capture_calls["camera_source"] = camera_source
        capture_calls["crop_output_path"] = crop_output_path
        capture_calls["postgres_writer"] = postgres_writer
        return pictures_root / "2026-03-30" / "2026-03-30_18-00-00.jpg", "123.4", timestamp or datetime.now()

    def stop_after_first_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_first_sleep)

    exit_code = app.main(
        [
            "--source",
            "ip",
            "--ip-camera-url",
            stream_url,
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--csv-file",
            str(tmp_path / "readings.csv"),
            "--interval",
            "1",
        ]
    )

    assert exit_code == 0
    assert capture_calls["camera"] is None
    assert capture_calls["camera_source"] == CameraSource("ip", stream_url)
    assert capture_calls["crop_output_path"] is None
    assert capture_calls["postgres_writer"] is None

    out = capsys.readouterr().out
    assert "source=ip(url=rtsp://admin:***@192.168.10.31:554/stream1)" in out
    assert "value=123.4" in out


def test_main_persists_first_then_every_nth_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persist_calls: list[bool] = []

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        csv_path: Path,
        *,
        timestamp: datetime | None = None,
        camera_source: CameraSource | None = None,
        crop_rect: CropRect | None = None,
        picture_type: str = "auto",
        debug_output_dir: Path | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        postgres_writer: object | None = None,
        ocr_func=app.extract_value_from_prepared_image,
    ) -> tuple[Path | None, str | None, datetime]:
        persist_calls.append(persist_image)
        call_number = len(persist_calls)
        ts = datetime(2026, 3, 30, 18, 0, call_number)
        if persist_image:
            image_path: Path | None = pictures_root / f"capture-{call_number}.jpg"
        else:
            image_path = None
        return image_path, f"100.{call_number}", ts

    sleep_calls = 0

    def stop_after_third_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_third_sleep)

    exit_code = app.main(
        [
            "--source",
            "ip",
            "--ip-camera-url",
            "rtsp://camera/stream1",
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--csv-file",
            str(tmp_path / "readings.csv"),
            "--persist-every",
            "2",
            "--interval",
            "1",
        ]
    )

    assert exit_code == 0
    assert persist_calls == [True, False, True]

    out = capsys.readouterr().out
    assert "persist_every=2" in out
    assert "saved=<skipped> value=100.2" in out


def test_main_initializes_postgres_writer_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created_targets: list[PostgresTarget] = []
    persisted_writers: list[object | None] = []

    class FakePostgresWriter:
        def __init__(self, target: PostgresTarget) -> None:
            created_targets.append(target)

        def connect(self) -> None:
            return None

        def close(self) -> None:
            return None

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        csv_path: Path,
        *,
        timestamp: datetime | None = None,
        camera_source: CameraSource | None = None,
        crop_rect: CropRect | None = None,
        picture_type: str = "auto",
        debug_output_dir: Path | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        postgres_writer: object | None = None,
        ocr_func=app.extract_value_from_prepared_image,
    ) -> tuple[Path | None, str | None, datetime]:
        persisted_writers.append(postgres_writer)
        return pictures_root / "capture.jpg", "111.4", timestamp or datetime.now()

    def stop_after_first_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "PostgresWriter", FakePostgresWriter)
    monkeypatch.setattr(app, "ensure_postgres_dependencies", lambda: None)
    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_first_sleep)

    exit_code = app.main(
        [
            "--source",
            "ip",
            "--ip-camera-url",
            "rtsp://camera/stream1",
            "--interval",
            "1",
            "--pg-write",
            "--pg-database-url",
            "postgres://meter:meter@db:5432/water_meter",
            "--pg-source",
            "camera-reader",
            "--pg-value-mode",
            "round",
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--csv-file",
            str(tmp_path / "readings.csv"),
        ]
    )

    assert exit_code == 0
    assert created_targets == [
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="camera-reader",
            value_mode="round",
        )
    ]
    assert len(persisted_writers) == 1

    out = capsys.readouterr().out
    assert "postgres=enabled(source=camera-reader, value_mode=round)" in out
