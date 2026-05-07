from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from app import CropRect, ManualReadResult, PostgresTarget, PostgresWriter, build_arg_parser, crop_image, manual_read_payload, normalize_ocr_text, parse_crop_output, parse_crop_rect, parse_postgres_target, run_capture_cycle, run_ollama_ocr


class FakeCamera:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()


def test_postgres_writer_persists_upsert_query() -> None:
    executed: dict[str, object] = {"queries": []}

    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
            executed["queries"].append((query, params))

        def fetchone(self) -> None:
            return None

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

    app._PSYCOPG_IMPORT_ERROR = None
    app.psycopg = SimpleNamespace(connect=fake_connect)

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
            anomaly_threshold=100,
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 20, 30), 12345)

    assert executed["database_url"] == "postgres://meter:meter@db:5432/water_meter"
    assert executed["autocommit"] is True
    queries = [item for item in executed["queries"] if item[1] is not None]
    assert len(queries) == 2
    assert "SELECT recorded_at, meter_value_m3" in str(queries[0][0])
    assert "INSERT INTO meter_readings" in str(queries[1][0])
    assert "ON CONFLICT (recorded_at) DO UPDATE" in str(queries[1][0])
    params = queries[1][1]
    assert isinstance(params, tuple)
    assert params[1:] == (12345, "reader-test")
    assert getattr(params[0], "tzinfo", None) is not None


def test_postgres_writer_skips_large_positive_jump_and_records_anomaly() -> None:
    executed: dict[str, object] = {"queries": []}

    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
            executed["queries"].append((query, params))

        def fetchone(self) -> tuple[datetime, int]:
            return (datetime(2026, 3, 16, 10, 15, 0), 1000)

    class FakeConnection:
        closed = False

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = True

    def fake_connect(database_url: str, autocommit: bool) -> FakeConnection:
        executed["database_url"] = database_url
        executed["autocommit"] = autocommit
        return FakeConnection()

    app._PSYCOPG_IMPORT_ERROR = None
    app.psycopg = SimpleNamespace(connect=fake_connect)

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
            anomaly_threshold=100,
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 20, 30), 1205)

    queries = [item for item in executed["queries"] if item[1] is not None]
    assert len(queries) == 2
    assert "SELECT recorded_at, meter_value_m3" in str(queries[0][0])
    assert "INSERT INTO meter_reading_anomalies" in str(queries[1][0])
    assert "INSERT INTO meter_readings" not in str(queries[1][0])
    params = queries[1][1]
    assert isinstance(params, tuple)
    assert params[1:] == (1205, datetime(2026, 3, 16, 10, 15, 0), 1000, 205, 100, "reader-test")


def test_postgres_writer_compares_against_previous_anomaly_before_accepting_next_reading() -> None:
    executed: dict[str, object] = {"queries": []}
    database = {
        "readings": [(datetime(2026, 3, 16, 9, 15, 0, tzinfo=timezone.utc), 1000)],
        "anomalies": [],
    }

    class FakeCursor:
        def __init__(self) -> None:
            self._fetchone_result: tuple[datetime, int] | None = None

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
            executed["queries"].append((query, params))
            if params is None:
                return

            if "SELECT recorded_at, meter_value_m3" in query:
                recorded_at = params[0]
                rows = list(database["readings"])
                if "meter_reading_anomalies" in query:
                    rows.extend(database["anomalies"])
                eligible = [row for row in rows if row[0] < recorded_at]
                self._fetchone_result = max(eligible, key=lambda row: row[0]) if eligible else None
                return

            if "INSERT INTO meter_reading_anomalies" in query:
                database["anomalies"].append((params[0], params[1]))
                return

            if "INSERT INTO meter_readings" in query:
                database["readings"].append((params[0], params[1]))

        def fetchone(self) -> tuple[datetime, int] | None:
            return self._fetchone_result

    class FakeConnection:
        closed = False

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = True

    def fake_connect(database_url: str, autocommit: bool) -> FakeConnection:
        executed["database_url"] = database_url
        executed["autocommit"] = autocommit
        return FakeConnection()

    app._PSYCOPG_IMPORT_ERROR = None
    app.psycopg = SimpleNamespace(connect=fake_connect)

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
            anomaly_threshold=100,
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 20, 0), 1205)
    writer.persist(datetime(2026, 3, 16, 10, 25, 0), 1210)

    queries = [item for item in executed["queries"] if item[1] is not None]
    assert len(queries) == 4
    assert "SELECT recorded_at, meter_value_m3" in str(queries[0][0])
    assert "INSERT INTO meter_reading_anomalies" in str(queries[1][0])
    assert "SELECT recorded_at, meter_value_m3" in str(queries[2][0])
    assert "INSERT INTO meter_readings" in str(queries[3][0])
    anomaly_params = queries[1][1]
    insert_params = queries[3][1]
    assert isinstance(anomaly_params, tuple)
    assert isinstance(insert_params, tuple)
    assert anomaly_params[1:] == (
        1205,
        datetime(2026, 3, 16, 9, 15, 0, tzinfo=timezone.utc),
        1000,
        205,
        100,
        "reader-test",
    )
    assert insert_params[1:] == (1210, "reader-test")


def test_postgres_writer_prefers_accepted_reading_when_timestamp_matches_previous_anomaly() -> None:
    executed: dict[str, object] = {"queries": []}
    database = {
        "readings": [(datetime(2026, 3, 16, 9, 20, 0, tzinfo=timezone.utc), 1206)],
        "anomalies": [(datetime(2026, 3, 16, 9, 20, 0, tzinfo=timezone.utc), 1205)],
    }

    class FakeCursor:
        def __init__(self) -> None:
            self._fetchone_result: tuple[datetime, int] | None = None

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
            executed["queries"].append((query, params))
            if params is None:
                return

            if "SELECT recorded_at, meter_value_m3" in query:
                recorded_at = params[0]
                rows = [(ts, value, 1) for ts, value in database["readings"]]
                if "meter_reading_anomalies" in query:
                    rows.extend((ts, value, 0) for ts, value in database["anomalies"])
                eligible = [row for row in rows if row[0] < recorded_at]
                latest = max(eligible, key=lambda row: (row[0], row[2])) if eligible else None
                self._fetchone_result = None if latest is None else (latest[0], latest[1])
                return

            if "INSERT INTO meter_reading_anomalies" in query:
                database["anomalies"].append((params[0], params[1]))
                return

            if "INSERT INTO meter_readings" in query:
                database["readings"].append((params[0], params[1]))

        def fetchone(self) -> tuple[datetime, int] | None:
            return self._fetchone_result

    class FakeConnection:
        closed = False

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = True

    def fake_connect(database_url: str, autocommit: bool) -> FakeConnection:
        executed["database_url"] = database_url
        executed["autocommit"] = autocommit
        return FakeConnection()

    app._PSYCOPG_IMPORT_ERROR = None
    app.psycopg = SimpleNamespace(connect=fake_connect)

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
            anomaly_threshold=10,
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 25, 0), 1214)

    queries = [item for item in executed["queries"] if item[1] is not None]
    assert len(queries) == 2
    assert "SELECT recorded_at, meter_value_m3" in str(queries[0][0])
    assert "INSERT INTO meter_readings" in str(queries[1][0])
    insert_params = queries[1][1]
    assert isinstance(insert_params, tuple)
    assert insert_params[1:] == (1214, "reader-test")


def test_normalize_ocr_text() -> None:
    assert normalize_ocr_text("12345") == "12345"
    assert normalize_ocr_text("current reading: 12,34 m3") == "1234"
    assert normalize_ocr_text("Meter value: 891.12") == "89112"
    assert normalize_ocr_text("abc") is None


def test_run_ollama_ocr_extracts_first_numeric_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    crop_path = tmp_path / "meter-crop.png"
    crop_path.write_bytes(b"test")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"response":"Meter value: 12345.67"}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        assert timeout == 120
        assert request.full_url == "http://127.0.0.1:11434/api/generate"
        return FakeResponse()

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)

    assert run_ollama_ocr(crop_path) == 1234567


def test_run_ollama_ocr_reports_missing_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    crop_path = tmp_path / "meter-crop.png"
    crop_path.write_bytes(b"test")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"response":"no digits here"}'

    monkeypatch.setattr(app.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="No numeric meter reading"):
        run_ollama_ocr(crop_path)


def test_run_ollama_ocr_reports_http_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    crop_path = tmp_path / "meter-crop.png"
    crop_path.write_bytes(b"test")

    class FakeHttpError(app.urllib.error.HTTPError):
        def read(self) -> bytes:
            return b'model failed'

    def fake_urlopen(*args, **kwargs):
        raise FakeHttpError("http://127.0.0.1:11434/api/generate", 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="model failed"):
        run_ollama_ocr(crop_path)


def test_run_ollama_ocr_reports_connection_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    crop_path = tmp_path / "meter-crop.png"
    crop_path.write_bytes(b"test")

    def fake_urlopen(*args, **kwargs):
        raise app.urllib.error.URLError("connection refused")

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Could not reach Ollama API"):
        run_ollama_ocr(crop_path)


def test_run_capture_cycle_writes_original_image(tmp_path: Path) -> None:
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    frame[5:15, 10:20] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 30)

    pictures_dir = tmp_path / "pictures"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        timestamp=timestamp,
        crop_rect=CropRect(10, 5, 20, 15),
        crop_output_path=tmp_path / "meter-crop.png",
        ocr_func=lambda path: 12345,
    )

    assert value == 12345
    assert ts == timestamp
    assert image_path == pictures_dir / "2026-03-16" / "2026-03-16_10-20-30.jpg"
    assert image_path.exists()

    saved = cv2.imread(str(image_path))
    assert saved is not None
    assert saved.shape == frame.shape
    assert int(saved[10, 15, 2]) >= 200
    assert int(saved[0, 0].max()) <= 10


def test_run_capture_cycle_persists_to_postgres_writer(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 45)
    calls: list[tuple[datetime, int]] = []

    class FakePostgresWriter:
        def persist(self, ts: datetime, value: int) -> None:
            calls.append((ts, value))

    _, value, ts = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        timestamp=timestamp,
        crop_rect=CropRect(1, 1, 10, 10),
        crop_output_path=tmp_path / "meter-crop.png",
        postgres_writer=FakePostgresWriter(),
        ocr_func=lambda path: 54321,
    )

    assert value == 54321
    assert ts == timestamp
    assert calls == [(timestamp, 54321)]


def test_run_capture_cycle_appends_configured_digit_before_persistence(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 45)
    calls: list[tuple[datetime, int]] = []

    class FakePostgresWriter:
        def persist(self, ts: datetime, value: int) -> None:
            calls.append((ts, value))

    _, value, ts = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        timestamp=timestamp,
        crop_rect=CropRect(1, 1, 10, 10),
        crop_output_path=tmp_path / "meter-crop.png",
        postgres_writer=FakePostgresWriter(),
        ocr_func=lambda path: 89112,
        ocr_append_digit=0,
    )

    assert value == 891120
    assert ts == timestamp
    assert calls == [(timestamp, 891120)]


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
        timestamp=timestamp,
        crop_rect=crop_rect,
        crop_output_path=crop_output,
        ocr_func=lambda path: 123,
    )

    saved = cv2.imread(str(crop_output))
    assert saved is not None
    np.testing.assert_array_equal(saved, crop_image(frame, crop_rect))


def test_run_capture_cycle_archives_processed_crop_when_original_is_persisted(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 20, 50)
    crop_rect = CropRect(8, 4, 22, 16)
    crop_output = tmp_path / "meter-crop.png"
    processed_dir = tmp_path / "processed"

    image_path, _, _ = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        timestamp=timestamp,
        crop_rect=crop_rect,
        crop_output_path=crop_output,
        processed_pictures_root=processed_dir,
        ocr_func=lambda path: 123,
    )

    assert image_path is not None
    archived_crop = processed_dir / "2026-03-16" / "2026-03-16_10-20-50.jpg"
    assert archived_crop.exists()

    saved = cv2.imread(str(archived_crop))
    assert saved is not None
    expected = crop_image(frame, crop_rect)
    assert saved.shape == expected.shape
    assert np.abs(saved.astype(np.int16) - expected.astype(np.int16)).max() <= 1


def test_run_capture_cycle_passes_written_crop_to_ocr(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[4:16, 8:22] = (0, 0, 255)
    camera = FakeCamera(frame)
    crop_rect = CropRect(8, 4, 22, 16)
    crop_output = tmp_path / "meter-crop.png"
    captured: dict[str, object] = {}

    def fake_ocr(path: Path) -> int:
        captured["path"] = path
        captured["bytes"] = path.read_bytes()
        return 777

    value = run_capture_cycle(
        camera,
        tmp_path / "pictures",
        timestamp=datetime(2026, 3, 16, 10, 21, 0),
        crop_rect=crop_rect,
        crop_output_path=crop_output,
        ocr_func=fake_ocr,
    )[1]

    assert value == 777
    assert captured["path"] == crop_output
    assert captured["bytes"] == crop_output.read_bytes()


def test_run_capture_cycle_without_persistence_still_returns_ocr_value(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 22, 0)

    pictures_dir = tmp_path / "pictures"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        timestamp=timestamp,
        crop_rect=CropRect(1, 1, 10, 10),
        crop_output_path=tmp_path / "meter-crop.png",
        persist_image=False,
        ocr_func=lambda path: 9001,
    )

    assert image_path is None
    assert value == 9001
    assert ts == timestamp
    assert not pictures_dir.exists()


def test_crop_image_uses_requested_rectangle() -> None:
    image = np.arange(6 * 8 * 3, dtype=np.uint8).reshape((6, 8, 3))

    cropped = crop_image(image, CropRect(2, 1, 6, 4))

    assert cropped.shape == (3, 4, 3)
    np.testing.assert_array_equal(cropped, image[1:4, 2:6])


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
        ]
    )

    assert parse_postgres_target(args, parser) == PostgresTarget(
        database_url="postgres://meter:meter@localhost:5432/water_meter",
        source="camera-reader",
        anomaly_threshold=100,
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
        anomaly_threshold=100,
    )


def test_parse_postgres_target_uses_explicit_anomaly_threshold() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--pg-write",
            "--pg-database-url",
            "postgres://meter:meter@localhost:5432/water_meter",
            "--pg-anomaly-threshold",
            "250",
        ]
    )

    assert parse_postgres_target(args, parser) == PostgresTarget(
        database_url="postgres://meter:meter@localhost:5432/water_meter",
        source="reader",
        anomaly_threshold=250,
    )


def test_parser_accepts_ocr_append_digit() -> None:
    parser = build_arg_parser()

    args = parser.parse_args(["--ocr-append-digit", "0"])

    assert args.ocr_append_digit == 0


def test_parse_postgres_target_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--pg-write"])
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit):
        parse_postgres_target(args, parser)


def test_parse_crop_output_defaults_to_disabled() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["--x1", "1", "--y1", "2", "--x2", "8", "--y2", "9"])

    assert parse_crop_output(args, CropRect(1, 2, 8, 9), parser) == Path("meter-crop.png")


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


def test_main_rejects_non_positive_persist_every() -> None:
    with pytest.raises(SystemExit):
        app.main(["--x1", "1", "--y1", "2", "--x2", "8", "--y2", "9", "--persist-every", "0"])


def test_main_requires_crop_coordinates() -> None:
    with pytest.raises(SystemExit):
        app.main([])


def test_main_reports_missing_python_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "_CV2_IMPORT_ERROR", ModuleNotFoundError("No module named 'cv2'"))
    monkeypatch.setattr(app, "find_project_python", lambda: Path(".venv/bin/python"))

    exit_code = app.main(["--interval", "3", "--x1", "1", "--y1", "2", "--x2", "8", "--y2", "9"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Missing Python dependency: opencv-python." in err
    assert "python3 -m pip install -r requirements.txt" in err
    assert ".venv/bin/python app.py ..." in err


def test_help_text_matches_usb_only_contract() -> None:
    help_text = build_arg_parser().format_help()

    assert "--camera-index CAMERA_INDEX" in help_text
    assert "--ocr-append-digit {0,1,2,3,4,5,6,7,8,9}" in help_text
    assert "--persist-every PERSIST_EVERY" in help_text
    assert "--crop-output CROP_OUTPUT" in help_text
    assert "--pg-write" in help_text
    assert "python3 app.py --camera-index 0" in help_text
    assert "/api/generate" in help_text
    assert "IP camera" not in help_text
    assert "--source" not in help_text
    assert "--csv-file" not in help_text
    assert "--no-csv" not in help_text
    assert "--picture-type" not in help_text
    assert "--ocr-preprocess" not in help_text


def test_main_uses_usb_camera_and_logs_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture_calls: dict[str, object] = {}

    class FakeOpenedCamera:
        def release(self) -> None:
            capture_calls["released"] = True

    def fake_open_camera(camera_index: int) -> FakeOpenedCamera:
        capture_calls["camera_index"] = camera_index
        return FakeOpenedCamera()

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        *,
        timestamp: datetime | None = None,
        crop_rect: CropRect | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        processed_pictures_root: Path | None = None,
        postgres_writer: object | None = None,
        ocr_append_digit: int | None = None,
    ) -> tuple[Path | None, int, datetime]:
        capture_calls["camera"] = camera
        capture_calls["crop_rect"] = crop_rect
        capture_calls["persist_image"] = persist_image
        capture_calls["crop_output_path"] = crop_output_path
        capture_calls["processed_pictures_root"] = processed_pictures_root
        capture_calls["postgres_writer"] = postgres_writer
        capture_calls["ocr_append_digit"] = ocr_append_digit
        return pictures_root / "2026-03-30" / "2026-03-30_18-00-00.jpg", 12345, datetime(2026, 3, 30, 18, 0, 0)

    def stop_after_first_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "open_camera", fake_open_camera)
    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_first_sleep)

    exit_code = app.main(
        [
            "--camera-index",
            "2",
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--x1",
            "1",
            "--y1",
            "2",
            "--x2",
            "8",
            "--y2",
            "9",
            "--interval",
            "1",
        ]
    )

    assert exit_code == 0
    assert capture_calls["camera_index"] == 2
    assert capture_calls["crop_rect"] == CropRect(1, 2, 8, 9)
    assert capture_calls["crop_output_path"] == Path("meter-crop.png")
    assert capture_calls["processed_pictures_root"] == Path("processed")
    assert capture_calls["postgres_writer"] is None
    assert capture_calls["ocr_append_digit"] is None
    assert capture_calls["persist_image"] is True
    assert capture_calls["released"] is True

    out = capsys.readouterr().out
    assert "source=usb(index=2)" in out
    assert "value=12345" in out


def test_main_persists_first_then_every_nth_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persist_calls: list[bool] = []

    class FakeOpenedCamera:
        def release(self) -> None:
            return None

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        *,
        timestamp: datetime | None = None,
        crop_rect: CropRect | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        processed_pictures_root: Path | None = None,
        postgres_writer: object | None = None,
        ocr_append_digit: int | None = None,
    ) -> tuple[Path | None, int, datetime]:
        persist_calls.append(persist_image)
        call_number = len(persist_calls)
        ts = datetime(2026, 3, 30, 18, 0, call_number)
        if persist_image:
            image_path: Path | None = pictures_root / f"capture-{call_number}.jpg"
        else:
            image_path = None
        return image_path, 20000 + call_number, ts

    sleep_calls = 0

    def stop_after_third_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(app, "open_camera", lambda _camera_index: FakeOpenedCamera())
    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_third_sleep)

    exit_code = app.main(
        [
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--x1",
            "1",
            "--y1",
            "2",
            "--x2",
            "8",
            "--y2",
            "9",
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
    assert "saved=<skipped> value=20002" in out


def test_main_initializes_postgres_writer_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created_targets: list[PostgresTarget] = []
    persisted_writers: list[object | None] = []

    class FakeOpenedCamera:
        def release(self) -> None:
            return None

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
        *,
        timestamp: datetime | None = None,
        crop_rect: CropRect | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        processed_pictures_root: Path | None = None,
        postgres_writer: object | None = None,
        ocr_append_digit: int | None = None,
    ) -> tuple[Path | None, int, datetime]:
        persisted_writers.append(postgres_writer)
        return pictures_root / "capture.jpg", 33333, datetime(2026, 3, 30, 18, 0, 0)

    def stop_after_first_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "open_camera", lambda _camera_index: FakeOpenedCamera())
    monkeypatch.setattr(app, "PostgresWriter", FakePostgresWriter)
    monkeypatch.setattr(app, "ensure_postgres_dependencies", lambda: None)
    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)
    monkeypatch.setattr(app.time, "sleep", stop_after_first_sleep)

    exit_code = app.main(
        [
            "--interval",
            "1",
            "--pg-write",
            "--pg-database-url",
            "postgres://meter:meter@db:5432/water_meter",
            "--pg-source",
            "camera-reader",
            "--pictures-dir",
            str(tmp_path / "pictures"),
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
    assert created_targets == [
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="camera-reader",
            anomaly_threshold=100,
        )
    ]
    assert len(persisted_writers) == 1

    out = capsys.readouterr().out
    assert "postgres=enabled(source=camera-reader)" in out


def test_manual_read_argument_is_parsed() -> None:
    args = build_arg_parser().parse_args(["--manual-read"])

    assert args.manual_read is True


def test_manual_read_payload_uses_expected_contract() -> None:
    payload = manual_read_payload(
        ManualReadResult(
            recorded_at=datetime(2026, 3, 16, 10, 20, 50, tzinfo=timezone.utc),
            meter_value_m3=12345,
            image_path=Path("pictures/2026-03-16/2026-03-16_10-20-50.jpg"),
            crop_path=Path("processed/2026-03-16/2026-03-16_10-20-50.jpg"),
        )
    )

    assert payload == {
        "recorded_at": "2026-03-16T10:20:50Z",
        "meter_value_m3": 12345,
        "image_path": "pictures/2026-03-16/2026-03-16_10-20-50.jpg",
        "crop_path": "processed/2026-03-16/2026-03-16_10-20-50.jpg",
    }


def test_main_manual_read_forces_image_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture_calls: dict[str, object] = {}

    class FakeOpenedCamera:
        def release(self) -> None:
            capture_calls["released"] = True

    def fake_run_capture_cycle(
        camera: object,
        pictures_root: Path,
        *,
        timestamp: datetime | None = None,
        crop_rect: CropRect | None = None,
        persist_image: bool = True,
        crop_output_path: Path | None = None,
        processed_pictures_root: Path | None = None,
        postgres_writer: object | None = None,
        ocr_append_digit: int | None = None,
    ) -> tuple[Path | None, int, datetime]:
        capture_calls["camera"] = camera
        capture_calls["crop_rect"] = crop_rect
        capture_calls["persist_image"] = persist_image
        capture_calls["crop_output_path"] = crop_output_path
        capture_calls["processed_pictures_root"] = processed_pictures_root
        capture_calls["postgres_writer"] = postgres_writer
        capture_calls["ocr_append_digit"] = ocr_append_digit
        return pictures_root / "2026-03-30" / "2026-03-30_18-00-00.jpg", 45678, datetime(2026, 3, 30, 18, 0, 0)

    monkeypatch.setattr(app, "open_camera", lambda _camera_index: FakeOpenedCamera())
    monkeypatch.setattr(app, "run_capture_cycle", fake_run_capture_cycle)

    exit_code = app.main(
        [
            "--manual-read",
            "--persist-every",
            "50",
            "--pictures-dir",
            str(tmp_path / "pictures"),
            "--processed-pictures-dir",
            str(tmp_path / "processed"),
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
    assert capture_calls["crop_rect"] == CropRect(1, 2, 8, 9)
    assert capture_calls["persist_image"] is True
    assert capture_calls["crop_output_path"] == Path("meter-crop.png")
    assert capture_calls["processed_pictures_root"] == tmp_path / "processed"
    assert capture_calls["released"] is True

    out = capsys.readouterr().out
    assert "manual read complete" in out
    assert "value=45678" in out
