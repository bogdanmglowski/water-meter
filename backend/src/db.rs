use sqlx::PgPool;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgExecutor;
use time::OffsetDateTime;

use crate::models::DbReading;

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
        SELECT id, recorded_at, meter_value_m3, source
        FROM meter_readings
        WHERE ($1::timestamptz IS NULL OR recorded_at >= $1)
          AND ($2::timestamptz IS NULL OR recorded_at <= $2)
        ORDER BY recorded_at ASC, id ASC
        OFFSET $3
        LIMIT $4
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

pub async fn fetch_window_readings(
    pool: &PgPool,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Result<Vec<DbReading>, sqlx::Error> {
    let previous = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT id, recorded_at, meter_value_m3, source
        FROM meter_readings
        WHERE recorded_at < $1
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        "#,
    )
    .bind(from)
    .fetch_optional(pool)
    .await
    ?;

    let mut readings = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT id, recorded_at, meter_value_m3, source
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
