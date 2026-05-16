use sqlx::PgExecutor;
use sqlx::PgPool;
use sqlx::postgres::PgPoolOptions;
use time::OffsetDateTime;

use crate::error::{AppError, AppResult};
use crate::models::{DbAnomaly, DbReading};

pub async fn connect(database_url: &str) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(10)
        .connect(database_url)
        .await
}

pub async fn run_migrations(pool: &PgPool) -> anyhow::Result<()> {
    sqlx::migrate!("./migrations").run(pool).await?;
    Ok(())
}

pub async fn fetch_readings(
    executor: impl PgExecutor<'_>,
    from: Option<OffsetDateTime>,
    to: Option<OffsetDateTime>,
    offset: i64,
    limit: i64,
) -> Result<Vec<DbReading>, sqlx::Error> {
    sqlx::query_as::<_, DbReading>(
        r#"
        WITH selected AS (
            SELECT id, recorded_at, meter_value_m3, source
            FROM meter_readings
            WHERE ($1::timestamptz IS NULL OR recorded_at >= $1)
              AND ($2::timestamptz IS NULL OR recorded_at <= $2)
            ORDER BY recorded_at ASC, id ASC
            OFFSET $3
            LIMIT $4
        )
        SELECT
            selected.id,
            selected.recorded_at,
            selected.meter_value_m3,
            selected.meter_value_m3 - previous_row.meter_value_m3 AS delta_m3,
            selected.source
        FROM selected
        LEFT JOIN LATERAL (
            SELECT meter_value_m3
            FROM meter_readings
            WHERE recorded_at < selected.recorded_at
               OR (recorded_at = selected.recorded_at AND id < selected.id)
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
        ) AS previous_row ON true
        ORDER BY selected.recorded_at ASC, selected.id ASC
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(offset)
    .bind(limit)
    .fetch_all(executor)
    .await
}

pub async fn count_readings(
    executor: impl PgExecutor<'_>,
    from: Option<OffsetDateTime>,
    to: Option<OffsetDateTime>,
) -> Result<i64, sqlx::Error> {
    sqlx::query_scalar::<_, i64>(
        r#"
        SELECT COUNT(*)
        FROM meter_readings
        WHERE ($1::timestamptz IS NULL OR recorded_at >= $1)
          AND ($2::timestamptz IS NULL OR recorded_at <= $2)
        "#,
    )
    .bind(from)
    .bind(to)
    .fetch_one(executor)
    .await
}

pub async fn count_negative_delta_context_readings(
    executor: impl PgExecutor<'_>,
    from: OffsetDateTime,
    to: OffsetDateTime,
    context_size: i64,
) -> Result<i64, sqlx::Error> {
    sqlx::query_scalar::<_, i64>(
        r#"
        WITH ordered AS (
            SELECT
                id,
                recorded_at,
                ROW_NUMBER() OVER (ORDER BY recorded_at ASC, id ASC) AS row_num,
                meter_value_m3 - LAG(meter_value_m3) OVER (ORDER BY recorded_at ASC, id ASC) AS delta_m3
            FROM meter_readings
        ),
        negative_rows AS (
            SELECT row_num
            FROM ordered
            WHERE recorded_at >= $1
              AND recorded_at <= $2
              AND delta_m3 < 0
        ),
        context_rows AS (
            SELECT DISTINCT ordered.id
            FROM ordered
            JOIN negative_rows
              ON ordered.row_num BETWEEN negative_rows.row_num - $3 AND negative_rows.row_num + $3
        )
        SELECT COUNT(*)
        FROM context_rows
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(context_size)
    .fetch_one(executor)
    .await
}

pub async fn fetch_negative_delta_context_readings(
    executor: impl PgExecutor<'_>,
    from: OffsetDateTime,
    to: OffsetDateTime,
    context_size: i64,
    offset: i64,
    limit: i64,
) -> Result<Vec<DbReading>, sqlx::Error> {
    sqlx::query_as::<_, DbReading>(
        r#"
        WITH ordered AS (
            SELECT
                id,
                recorded_at,
                meter_value_m3,
                source,
                ROW_NUMBER() OVER (ORDER BY recorded_at ASC, id ASC) AS row_num,
                meter_value_m3 - LAG(meter_value_m3) OVER (ORDER BY recorded_at ASC, id ASC) AS delta_m3
            FROM meter_readings
        ),
        negative_rows AS (
            SELECT row_num
            FROM ordered
            WHERE recorded_at >= $1
              AND recorded_at <= $2
              AND delta_m3 < 0
        ),
        context_rows AS (
            SELECT DISTINCT ordered.row_num
            FROM ordered
            JOIN negative_rows
              ON ordered.row_num BETWEEN negative_rows.row_num - $3 AND negative_rows.row_num + $3
        ),
        paged_rows AS (
            SELECT ordered.id, ordered.recorded_at, ordered.meter_value_m3, ordered.delta_m3, ordered.source
            FROM ordered
            JOIN context_rows ON context_rows.row_num = ordered.row_num
            ORDER BY ordered.recorded_at ASC, ordered.id ASC
            OFFSET $4
            LIMIT $5
        )
        SELECT id, recorded_at, meter_value_m3, delta_m3, source
        FROM paged_rows
        ORDER BY recorded_at ASC, id ASC
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(context_size)
    .bind(offset)
    .bind(limit)
    .fetch_all(executor)
    .await
}

pub async fn delete_reading(pool: &PgPool, id: i64) -> Result<u64, sqlx::Error> {
    let result = sqlx::query(
        r#"
        DELETE FROM meter_readings
        WHERE id = $1
        "#,
    )
    .bind(id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected())
}

pub async fn fetch_anomalies(
    pool: &PgPool,
    from: Option<OffsetDateTime>,
    to: Option<OffsetDateTime>,
    include_archived: bool,
) -> Result<Vec<DbAnomaly>, sqlx::Error> {
    sqlx::query_as::<_, DbAnomaly>(
        r#"
        SELECT
            anomaly.id,
            anomaly.recorded_at,
            anomaly.meter_value_m3,
            anomaly.previous_recorded_at,
            anomaly.previous_meter_value_m3,
            anomaly.delta_m3,
            anomaly.threshold_m3,
            anomaly.source,
            anomaly.image_path,
            anomaly.archived_at,
            anomaly.created_at,
            raw_reading.id AS raw_reading_id
        FROM meter_reading_anomalies AS anomaly
        LEFT JOIN meter_readings AS raw_reading
          ON raw_reading.recorded_at = anomaly.recorded_at
         AND raw_reading.meter_value_m3 = anomaly.meter_value_m3
        WHERE ($1::timestamptz IS NULL OR anomaly.recorded_at >= $1)
          AND ($2::timestamptz IS NULL OR anomaly.recorded_at <= $2)
          AND ($3::bool OR anomaly.archived_at IS NULL)
        ORDER BY anomaly.recorded_at DESC, anomaly.id DESC
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(include_archived)
    .fetch_all(pool)
    .await
}

pub async fn add_anomaly_to_raw_readings(pool: &PgPool, id: i64) -> AppResult<Option<i64>> {
    let anomaly = sqlx::query_as::<_, (OffsetDateTime, i64, String)>(
        r#"
        SELECT recorded_at, meter_value_m3, source
        FROM meter_reading_anomalies
        WHERE id = $1
        "#,
    )
    .bind(id)
    .fetch_optional(pool)
    .await?;

    let Some((recorded_at, meter_value_m3, source)) = anomaly else {
        return Ok(None);
    };

    let previous_value = sqlx::query_scalar::<_, i64>(
        r#"
        SELECT meter_value_m3
        FROM meter_readings
        WHERE recorded_at < $1
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        "#,
    )
    .bind(recorded_at)
    .fetch_optional(pool)
    .await?;

    let next_value = sqlx::query_scalar::<_, i64>(
        r#"
        SELECT meter_value_m3
        FROM meter_readings
        WHERE recorded_at > $1
        ORDER BY recorded_at ASC, id ASC
        LIMIT 1
        "#,
    )
    .bind(recorded_at)
    .fetch_optional(pool)
    .await?;

    if !raw_reading_fits_monotonic_sequence(previous_value, meter_value_m3, next_value) {
        return Err(AppError::BadRequest(
            "raw readings must stay non-decreasing; this anomaly remains archived-only"
                .to_owned(),
        ));
    }

    let reading_id = sqlx::query_scalar::<_, i64>(
        r#"
        INSERT INTO meter_readings (recorded_at, meter_value_m3, source)
        VALUES ($1, $2, $3)
        ON CONFLICT (recorded_at) DO UPDATE
        SET meter_value_m3 = EXCLUDED.meter_value_m3,
            source = EXCLUDED.source
        RETURNING id
        "#,
    )
    .bind(recorded_at)
    .bind(meter_value_m3)
    .bind(source)
    .fetch_one(pool)
    .await?;

    Ok(Some(reading_id))
}

fn raw_reading_fits_monotonic_sequence(
    previous_value: Option<i64>,
    candidate_value: i64,
    next_value: Option<i64>,
) -> bool {
    if previous_value.is_some_and(|previous| candidate_value < previous) {
        return false;
    }

    if next_value.is_some_and(|next| candidate_value > next) {
        return false;
    }

    true
}

pub async fn archive_anomaly(pool: &PgPool, id: i64) -> Result<Option<i64>, sqlx::Error> {
    sqlx::query_scalar::<_, i64>(
        r#"
        UPDATE meter_reading_anomalies
        SET archived_at = COALESCE(archived_at, NOW())
        WHERE id = $1
        RETURNING id
        "#,
    )
    .bind(id)
    .fetch_optional(pool)
    .await
}

pub async fn unarchive_anomaly(pool: &PgPool, id: i64) -> Result<Option<i64>, sqlx::Error> {
    sqlx::query_scalar::<_, i64>(
        r#"
        UPDATE meter_reading_anomalies
        SET archived_at = NULL
        WHERE id = $1
        RETURNING id
        "#,
    )
    .bind(id)
    .fetch_optional(pool)
    .await
}

pub async fn count_anomalies(
    pool: &PgPool,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Result<i64, sqlx::Error> {
    sqlx::query_scalar::<_, i64>(
        r#"
        SELECT COUNT(*)
        FROM meter_reading_anomalies
        WHERE recorded_at >= $1
          AND recorded_at <= $2
          AND archived_at IS NULL
        "#,
    )
    .bind(from)
    .bind(to)
    .fetch_one(pool)
    .await
}

pub async fn fetch_window_readings(
    pool: &PgPool,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Result<Vec<DbReading>, sqlx::Error> {
    let previous = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT id, recorded_at, meter_value_m3, NULL::bigint AS delta_m3, source
        FROM meter_readings
        WHERE recorded_at < $1
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        "#,
    )
    .bind(from)
    .fetch_optional(pool)
    .await?;

    let mut readings = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT id, recorded_at, meter_value_m3, NULL::bigint AS delta_m3, source
        FROM meter_readings
        WHERE recorded_at >= $1
          AND recorded_at <= $2
        ORDER BY recorded_at ASC, id ASC
        "#,
    )
    .bind(from)
    .bind(to)
    .fetch_all(pool)
    .await?;

    if let Some(previous) = previous {
        readings.insert(0, previous);
    }

    Ok(readings)
}

#[cfg(test)]
mod tests {
    use super::raw_reading_fits_monotonic_sequence;

    #[test]
    fn raw_reading_rejects_value_smaller_than_previous() {
        assert!(!raw_reading_fits_monotonic_sequence(Some(1_205), 995, None));
    }

    #[test]
    fn raw_reading_rejects_value_larger_than_next() {
        assert!(!raw_reading_fits_monotonic_sequence(None, 1_205, Some(1_100)));
    }

    #[test]
    fn raw_reading_accepts_value_between_neighbors() {
        assert!(raw_reading_fits_monotonic_sequence(Some(1_000), 1_050, Some(1_100)));
    }
}
