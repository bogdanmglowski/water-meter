ALTER TABLE IF EXISTS meter_readings
    ALTER COLUMN meter_value_m3 TYPE BIGINT
    USING round(meter_value_m3::numeric)::bigint;

CREATE TABLE IF NOT EXISTS meter_readings (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL UNIQUE,
    meter_value_m3 BIGINT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_readings_recorded_at
    ON meter_readings (recorded_at);

CREATE TABLE IF NOT EXISTS meter_reading_anomalies (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL UNIQUE,
    meter_value_m3 BIGINT NOT NULL,
    previous_recorded_at TIMESTAMPTZ NOT NULL,
    previous_meter_value_m3 BIGINT NOT NULL,
    delta_m3 BIGINT NOT NULL,
    threshold_m3 BIGINT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_reading_anomalies_recorded_at
    ON meter_reading_anomalies (recorded_at DESC, id DESC);

TRUNCATE TABLE meter_readings RESTART IDENTITY;
TRUNCATE TABLE meter_reading_anomalies RESTART IDENTITY;

WITH bounds AS (
    SELECT
        date_trunc('day', now() - interval '2 years') AS start_at,
        date_trunc('day', now()) + interval '23 hours 50 minutes' AS end_at
),
readings AS (
    SELECT generate_series(start_at, end_at, interval '10 minutes') AS recorded_at
    FROM bounds
),
days AS (
    SELECT
        day_start,
        (1000 + floor(random() * 7000))::bigint AS daily_usage_liters
    FROM bounds
    CROSS JOIN generate_series(
        date_trunc('day', start_at),
        date_trunc('day', end_at),
        interval '1 day'
    ) AS gs(day_start)
),
ranked_readings AS (
    SELECT
        r.recorded_at,
        d.daily_usage_liters,
        row_number() OVER (
            PARTITION BY date_trunc('day', r.recorded_at)
            ORDER BY random()
        ) AS usage_rank
    FROM readings r
    JOIN days d
        ON d.day_start = date_trunc('day', r.recorded_at)
),
interval_usage AS (
    SELECT
        recorded_at,
        (daily_usage_liters / 144)
        + CASE
            WHEN usage_rank <= daily_usage_liters % 144 THEN 1::bigint
            ELSE 0::bigint
        END AS delta_m3
    FROM ranked_readings
),
cumulative AS (
    SELECT
        recorded_at,
        8459000 + COALESCE(SUM(delta_m3) OVER (
            ORDER BY recorded_at
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ), 0) AS meter_value_m3
    FROM interval_usage
)
INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
SELECT recorded_at, meter_value_m3, 'seed'
FROM cumulative
ORDER BY recorded_at;
