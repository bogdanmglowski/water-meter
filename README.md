# Water Meter

Browser-first water meter analytics for a single cumulative meter. An external process writes readings into PostgreSQL; this app reads them, derives consumption, highlights anomalies, and renders a responsive dashboard.

## Index

- [Overview](#overview)
- [Repository Modules](#repository-modules)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Build And Run](#build-and-run)
- [Project Cleanup](#project-cleanup)
- [Development Workflow](#development-workflow)
- [API](#api)

## Overview

This repository implements a read-only analytics app for one water meter.

The data model assumes cumulative meter readings, not per-interval usage. The backend converts those cumulative values into interval consumption, aggregates the results into hourly, daily, weekly, and monthly views, and produces alert signals for suspicious behavior such as spikes, overnight flow, or reset-like negative deltas.

The frontend is a responsive single-page dashboard intended to work well on desktop and phone. A single Docker Compose stack can build and run the full demo locally, and the same container stack is the recommended deployment model for a Linux host in a LAN.

## Repository Modules

### `backend/`

Rust API service for analytics and data access.

Responsibilities:
- connect to PostgreSQL
- run SQL migrations on startup
- read cumulative readings from `meter_readings`
- derive usage deltas between consecutive readings
- aggregate consumption into chart-ready time buckets
- detect alert conditions for spikes, overnight leak suspicion, and negative deltas
- expose JSON API endpoints and OpenAPI output

Important files:
- [backend/Cargo.toml](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/backend/Cargo.toml)
- [backend/src/main.rs](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/backend/src/main.rs)
- [backend/src/analytics.rs](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/backend/src/analytics.rs)
- [backend/src/db.rs](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/backend/src/db.rs)
- [backend/migrations/0001_init.sql](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/backend/migrations/0001_init.sql)

### `frontend/`

React dashboard for viewing water usage and anomalies.

Responsibilities:
- fetch dashboard, chart, alert, and raw reading data from the backend
- let the user switch date ranges and aggregation buckets
- render cumulative trend and interval consumption charts
- show summary cards for today, last 24 hours, last 7 days, and month-to-date
- display alert cards and a raw readings table
- build a static production bundle with Vite

Important files:
- [frontend/package.json](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/package.json)
- [frontend/src/App.tsx](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/src/App.tsx)
- [frontend/src/components/EChart.tsx](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/src/components/EChart.tsx)
- [frontend/src/api.ts](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/src/api.ts)
- [frontend/src/styles.css](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/src/styles.css)

### `infra/`

Infrastructure files for local Docker startup.

Responsibilities:
- define the local Docker Compose stack
- run PostgreSQL, the backend API, and the frontend client together
- provide the SQL seed used for test and demo data

Important files:
- [infra/docker-compose.yml](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/infra/docker-compose.yml)
- [infra/db/seed.sql](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/infra/db/seed.sql)

### `scripts/`

Helper scripts for local development.

Responsibilities:
- execute one-off project tasks that are easier to run from a shell wrapper than from raw commands
- currently includes demo data reseeding against the running PostgreSQL container

Important files:
- [scripts/seed-db.sh](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/scripts/seed-db.sh)

## Features

- summary cards for today, last 24 hours, last 7 days, and month-to-date
- cumulative meter trend chart
- consumption charts by hour, day, week, or month
- baseline-vs-actual daily view
- alerting for spikes, overnight leak suspicion, and negative deltas
- raw readings table with range filtering
- seed data generator for two years of 10-minute readings
- OpenAPI JSON output from the Rust backend

## Prerequisites

Install these tools before building or running the project:

- Rust toolchain with `cargo`
- Node.js 22+ with `npm`
- Docker with Docker Compose support
- `psql` is not required locally because the seed script runs inside the database container

## Configuration

1. Create a local environment file:

```bash
cp .env.example .env
```

2. Review the variables in `.env`:

- `DATABASE_URL`: backend connection string
- `APP_HOST`: backend bind host
- `APP_PORT`: backend bind port
- `CLIENT_HOST`: host name or LAN IP shown in container startup logs
- `CLIENT_PORT`: published frontend port
- `CLIENT_ORIGIN`: allowed frontend origin for backend CORS
- `POSTGRES_DB`: database name used by Docker and seed script
- `POSTGRES_USER`: database user
- `POSTGRES_PASSWORD`: database password
- `SEED_DEMO_DATA`: whether Docker startup should seed demo data into an empty database
- `VITE_API_BASE_URL`: optional explicit frontend API base URL

Default local behavior:
- Docker stack client: `http://localhost:5173`
- Docker stack API via frontend proxy: `http://localhost:5173/api`
- PostgreSQL stays on the internal Docker network in the ready-to-use stack
- `VITE_API_BASE_URL` is only needed for manual frontend runs against a non-default API base

## Build And Run

### Ready-To-Use Stack

Start everything with one command:

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

Open the client in your browser:
- `http://localhost:5173`

Useful URLs:
- client: `http://localhost:5173`
- API health: `http://localhost:5173/api/health`
- OpenAPI: `http://localhost:5173/api/openapi.json`

Logs:

```bash
docker compose -f infra/docker-compose.yml logs -f
```

Notes:
- frontend startup logs print the client and API URLs
- the `seed` service loads demo data only when `SEED_DEMO_DATA=true` and `meter_readings` is empty

Stop the stack:

```bash
docker compose -f infra/docker-compose.yml down
```

If the default frontend port is busy, override it when starting the stack:

```bash
CLIENT_PORT=5174 docker compose -f infra/docker-compose.yml up --build -d
```

### Linux LAN Deployment

Use this when the app should run continuously on another Linux machine in your network.

1. Copy the repository to the target host, for example `/opt/water-meter`.
2. Install Docker Engine with the Docker Compose plugin.
3. Create a deployment env file:

```bash
cp .env.production.example .env.production
```

4. Edit `.env.production`:

- set `CLIENT_HOST` to the server LAN IP or DNS name
- set `CLIENT_URL`, `API_URL`, and `CLIENT_ORIGIN` to the same host
- set a real `POSTGRES_PASSWORD`
- keep `SEED_DEMO_DATA=false` unless this host should start with demo data

5. Start the stack:

```bash
./scripts/deploy.sh up
```

Optional demo bootstrap:

```bash
./scripts/deploy.sh up --demo
```

Operational commands:

```bash
./scripts/deploy.sh logs
./scripts/deploy.sh ps
./scripts/deploy.sh restart
./scripts/deploy.sh down
```

Deployment behavior:
- the frontend is the only published service
- `/api` is proxied internally to the Rust backend
- PostgreSQL remains private to the Docker network
- the backend is no longer published directly on a host port

Optional autostart with `systemd`:

```bash
sudo cp infra/systemd/water-meter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-meter.service
```

The provided service assumes the repository lives in `/opt/water-meter`. Adjust the `WorkingDirectory`, `ExecStart`, and `ExecStop` paths if you deploy it elsewhere.

### Manual Development

Use this only if `DATABASE_URL` points to a reachable PostgreSQL instance.

Backend:

```bash
cd backend
cargo check
cargo test
cargo run
```

Frontend:

```bash
cd frontend
npm install
npm run build
npm run dev
```

Manual frontend notes:
- Vite proxies `/api` to `http://localhost:8080`
- if `VITE_API_BASE_URL` is set, the frontend uses that explicit base URL

Manual reseed:

```bash
./scripts/seed-db.sh
```

This truncates and recreates `meter_readings` in the running Docker database.

## Project Cleanup

Clean build artifacts:

```bash
./scripts/clean.sh
```

Clean build artifacts and frontend dependencies:

```bash
./scripts/clean.sh --deps
```

Cleanup scope:
- default removes `backend/target` and `frontend/dist`
- `--deps` additionally removes `frontend/node_modules`

## Development Workflow

Recommended day-to-day workflow:

1. Use the Docker stack for the default ready-to-use setup.
2. Run `cargo test` in `backend/` when changing analytics or API code.
3. Run `npm run build` in `frontend/` when changing dashboard code.
4. Use manual `cargo run` and `npm run dev` only when you need service-level iteration outside Docker.

Validation commands that are useful during development:

```bash
cd backend
cargo check
cargo test
```

```bash
cd frontend
npm run build
```

```bash
docker compose -f infra/docker-compose.yml config
```

## API

Implemented endpoints:

- `GET /api/health`
- `GET /api/dashboard?tz_offset_minutes=120`
- `GET /api/readings?from=...&to=...&limit=120`
- `GET /api/series/cumulative?from=...&to=...`
- `GET /api/series/consumption?from=...&to=...&bucket=day`
- `GET /api/alerts?from=...&to=...&tz_offset_minutes=120`
- `GET /api/openapi.json`

Endpoint intent:

- `/api/health`: simple health check
- `/api/dashboard`: summary cards and latest reading
- `/api/readings`: raw cumulative readings for inspection
- `/api/series/cumulative`: chart series for the raw meter register
- `/api/series/consumption`: aggregated derived usage for hour/day/week/month
- `/api/alerts`: anomaly and leak/spike signals for the selected window
- `/api/openapi.json`: generated API description
