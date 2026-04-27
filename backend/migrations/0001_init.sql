CREATE TABLE IF NOT EXISTS meter_readings (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL UNIQUE,
    meter_value_m3 BIGINT NOT NULL,
    source TEXT NOT NULL DEFAULT 'external',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_readings_recorded_at
    ON meter_readings (recorded_at);
