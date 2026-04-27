# Water Meter

Browser-first water meter analytics for a single cumulative meter. An external process writes readings into PostgreSQL; this app reads them, derives consumption, highlights anomalies, and renders a responsive dashboard.

## Index

- [Overview](#overview)
- [Repository Modules](#repository-modules)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Build And Run](#build-and-run)
- [Development Workflow](#development-workflow)
- [API](#api)

## Overview

This repository implements a read-only analytics app for one water meter.

The data model assumes cumulative meter readings, not per-interval usage. The backend converts those cumulative values into interval consumption, aggregates the results into hourly, daily, weekly, and monthly views, and produces alert signals for suspicious behavior such as spikes, overnight flow, or reset-like negative deltas.

The frontend is a responsive single-page dashboard intended to work well on desktop and phone. PostgreSQL runs separately in Docker, and a seed script is included so the app can be exercised without a real meter reader.

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

Infrastructure files for local database startup and test data.

Responsibilities:
- define the local PostgreSQL container
- declare database credentials and port mapping
- provide the SQL seed used for test and demo data

Important files:
- [infra/docker-compose.yml](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/infra/docker-compose.yml)
- [infra/db/seed.sql](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/infra/db/seed.sql)

### `scripts/`

Helper scripts for local development.

Responsibilities:
- execute one-off project tasks that are easier to run from a shell wrapper than from raw commands
- currently includes database seeding against the running PostgreSQL container

Important files:
- [scripts/seed-db.sh](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/scripts/seed-db.sh)

## Features

- summary cards for today, last 24 hours, last 7 days, and month-to-date
- cumulative meter trend chart
- consumption charts by hour, day, week, or month
- baseline-vs-actual daily view
- alerting for spikes, overnight leak suspicion, and negative deltas
- raw readings table with range filtering
- seed data generator for the last two months with noise and anomalies
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
- `CLIENT_ORIGIN`: allowed frontend origin for backend CORS
- `POSTGRES_DB`: database name used by Docker and seed script
- `POSTGRES_USER`: database user
- `POSTGRES_PASSWORD`: database password
- `VITE_API_BASE_URL`: optional explicit frontend API base URL

Default local behavior:
- PostgreSQL listens on `localhost:5432`
- backend listens on `http://localhost:8080`
- frontend dev server listens on `http://localhost:5173`

## Build And Run

### 1. Start PostgreSQL

Start the database container first. The backend depends on it.

```bash
docker compose -f infra/docker-compose.yml up -d
```

Check container status if needed:

```bash
docker compose -f infra/docker-compose.yml ps
```

Stop the database:

```bash
docker compose -f infra/docker-compose.yml down
```

### 2. Seed Test Data

Load two months of hourly readings with random noise and several anomalies.

What the seed currently includes:
- regular day and night usage variation
- slightly heavier weekend usage
- a few sharp spikes
- several overnight-flow windows
- one reset-like negative delta anomaly

Run the seed:

```bash
./scripts/seed-db.sh
```

This script:
- reads `.env` if present
- connects to the running `db` container
- recreates the demo data in `meter_readings`

### 3. Build The Backend

Compile the Rust API service:

```bash
cd backend
cargo build
```

Run backend tests:

```bash
cd backend
cargo test
```

Notes:
- migrations are executed automatically on startup
- the backend expects PostgreSQL to be reachable through `DATABASE_URL`

### 4. Run The Backend

Start the API locally:

```bash
cd backend
cargo run
```

When the backend is running, these URLs are relevant:
- `http://localhost:8080/api/health`
- `http://localhost:8080/api/openapi.json`

### 5. Build The Frontend

Install dependencies first:

```bash
cd frontend
npm install
```

Create a production build:

```bash
cd frontend
npm run build
```

The production bundle is written to:
- [frontend/dist](/home/bogdan/dev/workspaces/workspace_private_projects/water-meter/frontend/dist)

### 6. Run The Frontend

For local development with live reload:

```bash
cd frontend
npm run dev
```

For previewing the production build:

```bash
cd frontend
npm run preview
```

Notes:
- in dev mode, Vite proxies `/api` requests to `http://localhost:8080`
- if `VITE_API_BASE_URL` is set, the frontend uses that explicit base URL

### 7. Full Local Startup Order

Use this order for a clean local run:

1. `cp .env.example .env`
2. `docker compose -f infra/docker-compose.yml up -d`
3. `./scripts/seed-db.sh`
4. `cd backend && cargo run`
5. `cd frontend && npm install`
6. `cd frontend && npm run dev`

## Development Workflow

Recommended day-to-day workflow:

1. Start PostgreSQL with Docker.
2. Seed demo data if you need a known dataset.
3. Run `cargo test` in `backend/` when changing analytics or API code.
4. Run `npm run build` in `frontend/` when changing dashboard code.
5. Use `cargo run` and `npm run dev` together for interactive local development.

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
