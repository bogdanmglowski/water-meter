ALTER TABLE meter_readings
    ALTER COLUMN meter_value_m3 TYPE BIGINT
    USING round(meter_value_m3::numeric)::bigint;
