![Water Meter dashboard screenshot](docs/water-meter.png)

# Water Meter

Dashboards and anomaly detection for a single cumulative water meter. An external process (USB camera + OCR reader, or any other writer) periodically inserts cumulative register values into PostgreSQL. The backend converts those raw readings into interval consumption, aggregates into hourly/daily/weekly/monthly views, detects spikes, overnight leaks, and negative deltas, and exposes everything over a JSON API. The frontend renders a responsive dashboard with summary cards, consumption charts, alert cards, and a raw readings table. A bit of my code and a bit of code from various agents. 

- [Components](#components)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [Configuration](#configuration)

## Components

- **backend** -- Rust API that reads cumulative meter readings from PostgreSQL, derives interval consumption, aggregates into time buckets, and exposes JSON endpoints with OpenAPI output.
- **frontend** -- React SPA (Vite) that fetches dashboard data, renders consumption charts (ECharts), summary cards, alert cards, and a raw readings table with date-range and bucket controls.
- **infra** -- Docker Compose stack that runs PostgreSQL, the backend, frontend (behind Nginx), and an optional seed container for demo data.
- **reader** -- Python app that captures USB camera frames, crops the meter display, OCRs it via Ollama (`glm-ocr`), and optionally writes the recognized value to PostgreSQL with configurable anomaly threshold.

## Quick Start

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

Open `http://localhost:5173`.

## Deployment

For a LAN Linux host, copy the repo to `/opt/water-meter`, configure `.env`, then use the deploy script:

```bash
./scripts/deploy.sh up          # base stack
./scripts/deploy.sh up --reader # with camera reader
./scripts/deploy.sh backup      # database dump
```

Optional systemd autostart:

```bash
sudo cp infra/systemd/water-meter.service /etc/systemd/system/
sudo systemctl enable --now water-meter.service
```

## Configuration

Copy `.env.example` to `.env` and adjust the variables below.

### Backend & Frontend

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgres://water_meter:water_meter@localhost:5432/water_meter` | Backend PostgreSQL connection string |
| `APP_HOST` | `0.0.0.0` | Backend bind address |
| `APP_PORT` | `8080` | Backend bind port |
| `CLIENT_HOST` | `192.168.1.34` | Hostname or LAN IP shown in container startup logs |
| `CLIENT_PORT` | `88` | Published frontend port (e.g. `88`, `5173`) |
| `CLIENT_ORIGIN` | `http://192.168.1.34` | Allowed CORS origin for the backend (must match the browser's address exactly) |
| `API_URL` | `http://192.168.1.34/api/health` | Health check URL logged at startup |
| `RUST_LOG` | `info,tower_http=info` | Rust backend log level |
| `VITE_API_BASE_URL` | _(unset)_ | Override the API base URL for manual frontend runs outside Docker; when unset, Vite proxies `/api` to `localhost:8080` |

### Docker Stack

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB` | `water_meter` | PostgreSQL database name |
| `POSTGRES_USER` | `water_meter` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `water_meter` | PostgreSQL password |
| `WATER_METER_NETWORK` | `water-meter_default` | Docker network name used by the stack |
| `WATER_METER_SUBNET` | `172.28.0.0/16` | Fixed Docker network subnet |
| `SEED_DEMO_DATA` | `false` | Seed demo data into an empty database on startup |
| `BACKUP_HOST_DIR` | `/tmp` | Host directory where `deploy.sh backup` writes PostgreSQL dumps |
| `BACKUP_WAIT_SECONDS` | `30` | Seconds the backup container waits before starting the dump |

### Reader (Camera OCR)

| Variable | Default | Description |
|---|---|---|
| `READER_RUNTIME_DIR` | `../reader/runtime` | Host path for current crop and archived reader images |
| `READER_IMAGE_RETENTION_DAYS` | `30` | Auto-delete archived images older than this many days |
| `READER_CONTROL_URL` | `http://reader:8090/manual-read` | URL for triggering a manual read on the reader container |
| `READER_CAMERA_INDEX` | `0` | OpenCV camera index |
| `READER_VIDEO_DEVICE` | `/dev/video0` | Host video device mapped into the container |
| `READER_INTERVAL_SECONDS` | `180` | Seconds between capture cycles |
| `READER_PROCESSED_PICTURES_DIR` | `/data/processed` | Container path for archived processed crop images |
| `READER_PERSIST_EVERY` | `10` | Save original frame to disk every Nth cycle (1 = every cycle) |
| `READER_CROP_OUTPUT` | `/data/meter-crop.png` | Container path for the crop file sent to Ollama |
| `READER_CONTROL_BIND` | `0.0.0.0:8090` | Reader control API bind address inside the container |
| `READER_CONTROL_PUBLISH` | `192.168.10.134:8090` | Reader control API host address and port published by Docker |
| `READER_X1`, `READER_Y1` | `159`, `331` | Crop top-left corner coordinates (required) |
| `READER_X2`, `READER_Y2` | `565`, `414` | Crop bottom-right corner coordinates (required) |
| `READER_PG_WRITE` | `true` | Write the recognized value into `meter_readings` |
| `READER_PG_SOURCE` | `reader-docker` | Value written into the `source` column on insert |
| `READER_PG_ANOMALY_THRESHOLD` | `200` | Skip inserts when the delta exceeds this value (negative deltas are always skipped); anomalies go to `meter_reading_anomalies` |
| `READER_OCR_APPEND_DIGIT` | `0` | Append this digit before storing the value (use when the physical meter omits the final liter digit) |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API base URL reachable from the reader container |
