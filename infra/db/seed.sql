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
        (1 + floor(random() * 7))::bigint AS daily_usage
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
        d.daily_usage,
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
        CASE
            WHEN usage_rank <= daily_usage THEN 1::bigint
            ELSE 0::bigint
        END AS delta_m3
    FROM ranked_readings
),
cumulative AS (
    SELECT
        recorded_at,
        8459 + COALESCE(SUM(delta_m3) OVER (
            ORDER BY recorded_at
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ), 0) AS meter_value_m3
    FROM interval_usage
)
INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
SELECT recorded_at, meter_value_m3, 'seed'
FROM cumulative
ORDER BY recorded_at;
