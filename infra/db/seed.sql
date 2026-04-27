CREATE TABLE IF NOT EXISTS meter_readings (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL UNIQUE,
    meter_value_m3 NUMERIC(12, 3) NOT NULL,
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
            WHEN extract(hour FROM recorded_at) BETWEEN 0 AND 4 THEN 0.008 + random() * 0.015
            WHEN extract(hour FROM recorded_at) BETWEEN 6 AND 8 THEN 0.040 + random() * 0.065
            WHEN extract(hour FROM recorded_at) BETWEEN 18 AND 22 THEN 0.055 + random() * 0.090
            ELSE 0.015 + random() * 0.040
        END
        + CASE
            WHEN extract(dow FROM recorded_at) IN (0, 6) THEN 0.020
            ELSE 0.000
        END AS delta_m3
    FROM hours
),
with_spikes AS (
    SELECT
        recorded_at,
        CASE
            WHEN recorded_at = date_trunc('hour', now() - interval '3 days') + interval '19 hours' THEN 0.900
            WHEN recorded_at = date_trunc('hour', now() - interval '12 days') + interval '7 hours' THEN 0.550
            WHEN recorded_at BETWEEN date_trunc('day', now() - interval '2 days')
                 AND date_trunc('day', now() - interval '2 days') + interval '4 hours'
                THEN 0.090 + random() * 0.030
            ELSE delta_m3
        END AS delta_m3
    FROM hourly_usage
),
cumulative AS (
    SELECT
        recorded_at,
        round(
            (85432.000 + SUM(delta_m3) OVER (ORDER BY recorded_at ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))::numeric,
            3
        ) AS meter_value_m3
    FROM with_spikes
),
with_reset AS (
    SELECT
        recorded_at,
        CASE
            WHEN recorded_at = date_trunc('hour', now() - interval '9 days') + interval '12 hours'
                THEN meter_value_m3 - 0.450
            ELSE meter_value_m3
        END AS meter_value_m3
    FROM cumulative
)
INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
SELECT recorded_at, meter_value_m3, 'seed'
FROM with_reset
ORDER BY recorded_at;
