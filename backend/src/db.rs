use sqlx::PgPool;
use sqlx::postgres::PgPoolOptions;
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
    pool: &PgPool,
    from: Option<OffsetDateTime>,
    to: Option<OffsetDateTime>,
    limit: i64,
    cursor: Option<OffsetDateTime>,
) -> Result<Vec<DbReading>, sqlx::Error> {
    sqlx::query_as::<_, DbReading>(
        r#"
        SELECT recorded_at, meter_value_m3, source
        FROM meter_readings
        WHERE ($1::timestamptz IS NULL OR recorded_at >= $1)
          AND ($2::timestamptz IS NULL OR recorded_at <= $2)
          AND ($3::timestamptz IS NULL OR recorded_at > $3)
        ORDER BY recorded_at ASC
        LIMIT $4
        "#,
    )
    .bind(from)
    .bind(to)
    .bind(cursor)
    .bind(limit)
    .fetch_all(pool)
    .await
}

pub async fn fetch_window_readings(
    pool: &PgPool,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Result<Vec<DbReading>, sqlx::Error> {
    let previous = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT recorded_at, meter_value_m3, source
        FROM meter_readings
        WHERE recorded_at < $1
        ORDER BY recorded_at DESC
        LIMIT 1
        "#,
    )
    .bind(from)
    .fetch_optional(pool)
    .await?;

    let mut readings = sqlx::query_as::<_, DbReading>(
        r#"
        SELECT recorded_at, meter_value_m3, source
        FROM meter_readings
        WHERE recorded_at >= $1
          AND recorded_at <= $2
        ORDER BY recorded_at ASC
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
