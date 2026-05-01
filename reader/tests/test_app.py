from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from app import CropRect, PostgresTarget, PostgresWriter, build_arg_parser, crop_image, parse_crop_output, parse_crop_rect, parse_postgres_target, run_capture_cycle


class FakeCamera:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()


def test_postgres_writer_persists_upsert_query() -> None:
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

    app._PSYCOPG_IMPORT_ERROR = None
    app.psycopg = SimpleNamespace(connect=fake_connect)

    writer = PostgresWriter(
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="reader-test",
        )
    )

    writer.persist(datetime(2026, 3, 16, 10, 20, 30), 1)

    assert executed["database_url"] == "postgres://meter:meter@db:5432/water_meter"
    assert executed["autocommit"] is True
    assert "INSERT INTO meter_readings" in str(executed["query"])
    assert "ON CONFLICT (recorded_at) DO UPDATE" in str(executed["query"])
    params = executed["params"]
    assert isinstance(params, tuple)
    assert params[1:] == (1, "reader-test")
    assert getattr(params[0], "tzinfo", None) is not None


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
    )

    assert value == 1
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
        postgres_writer=FakePostgresWriter(),
    )

    assert value == 1
    assert ts == timestamp
    assert calls == [(timestamp, 1)]


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
    )

    saved = cv2.imread(str(crop_output))
    assert saved is not None
    np.testing.assert_array_equal(saved, crop_image(frame, crop_rect))


def test_run_capture_cycle_without_persistence_still_returns_fixed_value(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    camera = FakeCamera(frame)
    timestamp = datetime(2026, 3, 16, 10, 22, 0)

    pictures_dir = tmp_path / "pictures"

    image_path, value, ts = run_capture_cycle(
        camera,
        pictures_dir,
        timestamp=timestamp,
        persist_image=False,
    )

    assert image_path is None
    assert value == 1
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


def test_main_rejects_non_positive_persist_every() -> None:
    with pytest.raises(SystemExit):
        app.main(["--persist-every", "0"])


def test_main_reports_missing_python_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "_CV2_IMPORT_ERROR", ModuleNotFoundError("No module named 'cv2'"))
    monkeypatch.setattr(app, "find_project_python", lambda: Path(".venv/bin/python"))

    exit_code = app.main(["--interval", "3"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Missing Python dependency: opencv-python." in err
    assert "python3 -m pip install -r requirements.txt" in err
    assert ".venv/bin/python app.py ..." in err


def test_help_text_matches_usb_only_contract() -> None:
    help_text = build_arg_parser().format_help()

    assert "--camera-index CAMERA_INDEX" in help_text
    assert "--persist-every PERSIST_EVERY" in help_text
    assert "--crop-output CROP_OUTPUT" in help_text
    assert "--pg-write" in help_text
    assert "python3 app.py --camera-index 0" in help_text
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
        postgres_writer: object | None = None,
    ) -> tuple[Path | None, int, datetime]:
        capture_calls["camera"] = camera
        capture_calls["crop_rect"] = crop_rect
        capture_calls["persist_image"] = persist_image
        capture_calls["crop_output_path"] = crop_output_path
        capture_calls["postgres_writer"] = postgres_writer
        return pictures_root / "2026-03-30" / "2026-03-30_18-00-00.jpg", 1, datetime(2026, 3, 30, 18, 0, 0)

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
            "--interval",
            "1",
        ]
    )

    assert exit_code == 0
    assert capture_calls["camera_index"] == 2
    assert capture_calls["crop_rect"] is None
    assert capture_calls["crop_output_path"] is None
    assert capture_calls["postgres_writer"] is None
    assert capture_calls["persist_image"] is True
    assert capture_calls["released"] is True

    out = capsys.readouterr().out
    assert "source=usb(index=2)" in out
    assert "value=1" in out


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
        postgres_writer: object | None = None,
    ) -> tuple[Path | None, int, datetime]:
        persist_calls.append(persist_image)
        call_number = len(persist_calls)
        ts = datetime(2026, 3, 30, 18, 0, call_number)
        if persist_image:
            image_path: Path | None = pictures_root / f"capture-{call_number}.jpg"
        else:
            image_path = None
        return image_path, 1, ts

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
    assert "saved=<skipped> value=1" in out


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
        postgres_writer: object | None = None,
    ) -> tuple[Path | None, int, datetime]:
        persisted_writers.append(postgres_writer)
        return pictures_root / "capture.jpg", 1, datetime(2026, 3, 30, 18, 0, 0)

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
        ]
    )

    assert exit_code == 0
    assert created_targets == [
        PostgresTarget(
            database_url="postgres://meter:meter@db:5432/water_meter",
            source="camera-reader",
        )
    ]
    assert len(persisted_writers) == 1

    out = capsys.readouterr().out
    assert "postgres=enabled(source=camera-reader)" in out
