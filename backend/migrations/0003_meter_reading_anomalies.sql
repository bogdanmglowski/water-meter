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
