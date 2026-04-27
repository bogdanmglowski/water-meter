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

TRUNCATE TABLE meter_readings RESTART IDENTITY;

WITH hours AS (
    SELECT generate_series(
        date_trunc('hour', now() - interval '60 days'),
        date_trunc('hour', now()),
        interval '1 hour'
    ) AS recorded_at
),
hourly_usage AS (
    SELECT
        recorded_at,
        CASE
            WHEN extract(hour FROM recorded_at) BETWEEN 0 AND 4 THEN floor(random() * 2)::int
            WHEN extract(hour FROM recorded_at) BETWEEN 6 AND 8 THEN 1 + floor(random() * 3)::int
            WHEN extract(hour FROM recorded_at) BETWEEN 18 AND 22 THEN 2 + floor(random() * 4)::int
            ELSE floor(random() * 3)::int
        END
        + CASE
            WHEN extract(dow FROM recorded_at) IN (0, 6) THEN 1
            ELSE 0
        END AS delta_m3
    FROM hours
),
with_spikes AS (
    SELECT
        recorded_at,
        CASE
            WHEN recorded_at = date_trunc('hour', now() - interval '3 days') + interval '19 hours' THEN 12
            WHEN recorded_at = date_trunc('hour', now() - interval '12 days') + interval '7 hours' THEN 8
            WHEN recorded_at BETWEEN date_trunc('day', now() - interval '2 days')
                 AND date_trunc('day', now() - interval '2 days') + interval '4 hours'
                THEN 4 + floor(random() * 2)::int
            ELSE delta_m3
        END AS delta_m3
    FROM hourly_usage
),
cumulative AS (
    SELECT
        recorded_at,
        85432 + SUM(delta_m3) OVER (
            ORDER BY recorded_at
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS meter_value_m3
    FROM with_spikes
),
with_reset AS (
    SELECT
        recorded_at,
        CASE
            WHEN recorded_at = date_trunc('hour', now() - interval '9 days') + interval '12 hours'
                THEN meter_value_m3 - 3
            ELSE meter_value_m3
        END AS meter_value_m3
    FROM cumulative
)
INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
SELECT recorded_at, meter_value_m3, 'seed'
FROM with_reset
ORDER BY recorded_at;
