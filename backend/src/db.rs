use sqlx::PgExecutor;
use sqlx::PgPool;
use sqlx::postgres::PgPoolOptions;
use time::OffsetDateTime;

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
            id,
            recorded_at,
            meter_value_m3,
            previous_recorded_at,
            previous_meter_value_m3,
            delta_m3,
            threshold_m3,
            source,
            image_path,
            archived_at,
            created_at
        FROM meter_reading_anomalies
        WHERE ($1::timestamptz IS NULL OR recorded_at >= $1)
          AND ($2::timestamptz IS NULL OR recorded_at <= $2)
          AND ($3::bool OR archived_at IS NULL)
        ORDER BY recorded_at DESC, id DESC
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(include_archived)
    .fetch_all(pool)
    .await
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
