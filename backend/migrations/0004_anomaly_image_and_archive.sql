ALTER TABLE meter_reading_anomalies
    ADD COLUMN IF NOT EXISTS image_path TEXT,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
