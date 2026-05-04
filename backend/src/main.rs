mod analytics;
mod config;
mod db;
mod error;
mod models;
mod reader_files;

use axum::extract::{Path, Query, State};
use axum::http::header;
use axum::http::{HeaderValue, Method};
use axum::response::IntoResponse;
use axum::routing::{delete, get};
use axum::{Json, Router};
use sqlx::PgPool;
use std::path::PathBuf;
use time::{Duration, OffsetDateTime, format_description::well_known::Rfc3339};
use tokio::net::TcpListener;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use utoipa::OpenApi;

use crate::analytics::Bucket;
use crate::config::Config;
use crate::error::{AppError, AppResult};
use crate::models::{
    AlertDto, AnomalyDto, ConsumptionQuery, DashboardQuery, DashboardResponse,
    DeleteReaderImageResponse, DeleteReadingResponse, HealthResponse, RangeQuery, ReaderGalleryQuery,
    ReaderGalleryResponse, ReadingDto, ReadingsPageDto, ReadingsQuery, UsagePoint,
};
use crate::reader_files::{build_gallery, delete_image, purge_old_images, resolve_image_path};

#[derive(Clone)]
struct AppState {
    pool: PgPool,
    reader_runtime_dir: PathBuf,
    reader_image_retention_days: u16,
}

#[derive(OpenApi)]
#[openapi(
    paths(
        health,
        dashboard,
        readings,
        delete_reading,
        delete_reader_image,
        anomalies,
        cumulative_series,
        consumption_series,
        alerts,
        reader_gallery,
        reader_image,
        openapi
    ),
    components(
        schemas(
            HealthResponse,
            ReadingDto,
            ReadingsPageDto,
            DeleteReadingResponse,
            DeleteReaderImageResponse,
            AnomalyDto,
            UsagePoint,
            AlertDto,
            DashboardResponse,
            ReaderGalleryResponse,
            crate::models::ReaderImageItem,
            crate::models::DashboardSummary,
            crate::models::AlertSeverity
        )
    ),
    tags(
        (name = "water-meter", description = "Water meter analytics API")
    )
)]
struct ApiDoc;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,tower_http=info".into()),
        )
        .init();

    let config = Config::from_env()?;
    let pool = db::connect(&config.database_url).await?;
    db::run_migrations(&pool).await?;
    let allowed_origin = HeaderValue::from_str(&config.client_origin)?;
    let now = OffsetDateTime::now_utc();
    if let Err(error) = purge_old_images(
        &config.reader_runtime_dir,
        now,
        config.reader_image_retention_days,
    ) {
        tracing::warn!(?error, "failed to purge old reader images during startup");
    }

    let state = AppState {
        pool,
        reader_runtime_dir: config.reader_runtime_dir,
        reader_image_retention_days: config.reader_image_retention_days,
    };
    spawn_reader_image_cleanup(
        state.reader_runtime_dir.clone(),
        state.reader_image_retention_days,
    );
    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/dashboard", get(dashboard))
        .route("/api/readings", get(readings))
        .route("/api/readings/{id}", delete(delete_reading))
        .route("/api/anomalies", get(anomalies))
        .route("/api/series/cumulative", get(cumulative_series))
        .route("/api/series/consumption", get(consumption_series))
        .route("/api/alerts", get(alerts))
        .route("/api/reader/gallery", get(reader_gallery))
        .route("/api/reader/images/{category}/{*path}", delete(delete_reader_image))
        .route("/api/reader/images/{category}/{*path}", get(reader_image))
        .route("/api/openapi.json", get(openapi))
        .with_state(state)
        .layer(
            CorsLayer::new()
                .allow_origin(allowed_origin)
                .allow_methods([Method::GET, Method::DELETE])
                .allow_headers(Any),
        )
        .layer(TraceLayer::new_for_http());

    let listener = TcpListener::bind(config.bind_addr).await?;
    tracing::info!("listening on http://{}", config.bind_addr);
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

#[utoipa::path(
    get,
    path = "/api/health",
    responses((status = 200, description = "Service health", body = HealthResponse))
)]
async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_owned(),
        timestamp: OffsetDateTime::now_utc(),
    })
}

#[utoipa::path(
    get,
    path = "/api/dashboard",
    responses((status = 200, description = "Dashboard summary", body = DashboardResponse))
)]
async fn dashboard(
    State(state): State<AppState>,
    Query(query): Query<DashboardQuery>,
) -> AppResult<Json<DashboardResponse>> {
    let now = OffsetDateTime::now_utc();
    let tz_offset_minutes = normalize_tz_offset(query.tz_offset_minutes);
    let from = now - Duration::days(120);
    let readings = db::fetch_window_readings(&state.pool, from, now).await?;
    let anomaly_count = usize::try_from(db::count_anomalies(&state.pool, from, now).await?)
        .map_err(|_| AppError::Internal("anomaly count overflow".to_owned()))?;
    let alerts = analytics::build_alerts(&readings, now, tz_offset_minutes, from, now);
    let response = analytics::build_dashboard(
        &readings,
        now,
        tz_offset_minutes,
        alerts.len(),
        anomaly_count,
    );
    Ok(Json(response))
}

#[utoipa::path(
    get,
    path = "/api/readings",
    responses((status = 200, description = "Raw readings", body = ReadingsPageDto))
)]
async fn readings(
    State(state): State<AppState>,
    Query(query): Query<ReadingsQuery>,
) -> AppResult<Json<ReadingsPageDto>> {
    let from = parse_optional_timestamp(query.from.as_deref())?;
    let to = parse_optional_timestamp(query.to.as_deref())?;
    validate_range(from, to)?;
    let requested_page = query.page.unwrap_or(1);
    let page_size = query.page_size.unwrap_or(30).clamp(1, 200);
    let mut transaction = state.pool.begin().await?;
    let total_count = usize::try_from(db::count_readings(&mut *transaction, from, to).await?)
        .map_err(|_| AppError::Internal("readings count overflow".to_owned()))?;
    let page = analytics::resolve_readings_page(requested_page, page_size, total_count);
    let rows = db::fetch_readings(
        &mut *transaction,
        from,
        to,
        i64::try_from(page.offset)
            .map_err(|_| AppError::Internal("readings offset overflow".to_owned()))?,
        i64::try_from(page.limit)
            .map_err(|_| AppError::Internal("page size overflow".to_owned()))?,
    )
    .await?;
    transaction.commit().await?;

    Ok(Json(analytics::build_readings_page(&rows, page)))
}

#[utoipa::path(
    delete,
    path = "/api/readings/{id}",
    params(("id" = i64, Path, description = "Reading id")),
    responses(
        (status = 200, description = "Reading deleted", body = DeleteReadingResponse),
        (status = 404, description = "Reading not found")
    )
)]
async fn delete_reading(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> AppResult<Json<DeleteReadingResponse>> {
    let deleted = db::delete_reading(&state.pool, id).await?;
    if deleted == 0 {
        return Err(AppError::NotFound(format!("reading {id} was not found")));
    }

    Ok(Json(DeleteReadingResponse { deleted: true, id }))
}

#[utoipa::path(
    get,
    path = "/api/anomalies",
    responses((status = 200, description = "Skipped anomaly readings", body = [AnomalyDto]))
)]
async fn anomalies(
    State(state): State<AppState>,
    Query(query): Query<RangeQuery>,
) -> AppResult<Json<Vec<AnomalyDto>>> {
    let from = parse_optional_timestamp(query.from.as_deref())?;
    let to = parse_optional_timestamp(query.to.as_deref())?;
    validate_range(from, to)?;
    let anomalies = db::fetch_anomalies(&state.pool, from, to).await?;
    Ok(Json(analytics::build_anomalies(&anomalies)))
}

#[utoipa::path(
    get,
    path = "/api/series/cumulative",
    responses((status = 200, description = "Cumulative reading series", body = [ReadingDto]))
)]
async fn cumulative_series(
    State(state): State<AppState>,
    Query(query): Query<RangeQuery>,
) -> AppResult<Json<Vec<ReadingDto>>> {
    let (from, to) = resolve_range(query.from.as_deref(), query.to.as_deref(), 30)?;
    let rows = db::fetch_readings(&state.pool, Some(from), Some(to), 0, 10_000).await?;
    Ok(Json(analytics::build_readings(&rows)))
}

#[utoipa::path(
    get,
    path = "/api/series/consumption",
    responses((status = 200, description = "Aggregated consumption series", body = [UsagePoint]))
)]
async fn consumption_series(
    State(state): State<AppState>,
    Query(query): Query<ConsumptionQuery>,
) -> AppResult<Json<Vec<UsagePoint>>> {
    let (from, to) = resolve_range(query.from.as_deref(), query.to.as_deref(), 30)?;
    let bucket = Bucket::from_query(query.bucket.as_deref()).map_err(AppError::BadRequest)?;
    let tz_offset_minutes = normalize_tz_offset(query.tz_offset_minutes);
    let rows = db::fetch_window_readings(&state.pool, from, to).await?;
    let points = analytics::build_consumption_series(&rows, bucket, tz_offset_minutes, from, to);
    Ok(Json(points))
}

#[utoipa::path(
    get,
    path = "/api/alerts",
    responses((status = 200, description = "Detected alerts", body = [AlertDto]))
)]
async fn alerts(
    State(state): State<AppState>,
    Query(query): Query<RangeQuery>,
) -> AppResult<Json<Vec<AlertDto>>> {
    let (from, to) = resolve_range(query.from.as_deref(), query.to.as_deref(), 30)?;
    let tz_offset_minutes = normalize_tz_offset(query.tz_offset_minutes);
    let rows = db::fetch_window_readings(&state.pool, from, to).await?;
    let alerts = analytics::build_alerts(
        &rows,
        OffsetDateTime::now_utc(),
        tz_offset_minutes,
        from,
        to,
    );
    Ok(Json(alerts))
}

#[utoipa::path(
    get,
    path = "/api/reader/gallery",
    responses((status = 200, description = "Reader image gallery", body = ReaderGalleryResponse))
)]
async fn reader_gallery(
    State(state): State<AppState>,
    Query(query): Query<ReaderGalleryQuery>,
) -> AppResult<Json<ReaderGalleryResponse>> {
    let page_size = query.page_size.unwrap_or(7).clamp(1, 31);
    Ok(Json(build_gallery(
        &state.reader_runtime_dir,
        query.original_page.unwrap_or(1),
        query.processed_page.unwrap_or(1),
        page_size,
    )?))
}

#[utoipa::path(
    delete,
    path = "/api/reader/images/{category}/{path}",
    params(
        ("category" = String, Path, description = "Image category: current, original, or processed"),
        ("path" = String, Path, description = "Relative image path")
    ),
    responses(
        (status = 200, description = "Reader image deleted", body = DeleteReaderImageResponse),
        (status = 404, description = "Reader image not found")
    )
)]
async fn delete_reader_image(
    State(state): State<AppState>,
    Path((category, path)): Path<(String, String)>,
) -> AppResult<Json<DeleteReaderImageResponse>> {
    delete_image(&state.reader_runtime_dir, &category, &path)?;
    Ok(Json(DeleteReaderImageResponse {
        deleted: true,
        category,
        path,
    }))
}

#[utoipa::path(
    get,
    path = "/api/reader/images/{category}/{path}",
    params(
        ("category" = String, Path, description = "Image category: current, original, or processed"),
        ("path" = String, Path, description = "Relative image path")
    ),
    responses(
        (status = 200, description = "Reader image file"),
        (status = 404, description = "Reader image not found")
    )
)]
async fn reader_image(
    State(state): State<AppState>,
    Path((category, path)): Path<(String, String)>,
) -> AppResult<impl IntoResponse> {
    let image_path = resolve_image_path(&state.reader_runtime_dir, &category, &path)?;
    let bytes = tokio::fs::read(&image_path)
        .await
        .map_err(|error| AppError::Internal(error.to_string()))?;
    let mime = mime_for_path(&image_path);

    Ok(([(header::CONTENT_TYPE, mime)], bytes))
}

#[utoipa::path(
    get,
    path = "/api/openapi.json",
    responses((status = 200, description = "OpenAPI document"))
)]
async fn openapi() -> Json<utoipa::openapi::OpenApi> {
    Json(ApiDoc::openapi())
}

fn parse_optional_timestamp(value: Option<&str>) -> AppResult<Option<OffsetDateTime>> {
    value
        .map(|value| OffsetDateTime::parse(value, &Rfc3339).map_err(AppError::from))
        .transpose()
}

fn resolve_range(
    from: Option<&str>,
    to: Option<&str>,
    default_days: i64,
) -> AppResult<(OffsetDateTime, OffsetDateTime)> {
    let now = OffsetDateTime::now_utc();
    let resolved_to = parse_optional_timestamp(to)?.unwrap_or(now);
    let resolved_from =
        parse_optional_timestamp(from)?.unwrap_or(resolved_to - Duration::days(default_days));
    validate_range(Some(resolved_from), Some(resolved_to))?;
    Ok((resolved_from, resolved_to))
}

fn validate_range(from: Option<OffsetDateTime>, to: Option<OffsetDateTime>) -> AppResult<()> {
    if let (Some(from), Some(to)) = (from, to) {
        if from > to {
            return Err(AppError::BadRequest(
                "`from` must be earlier than or equal to `to`".to_owned(),
            ));
        }
    }
    Ok(())
}

fn normalize_tz_offset(value: Option<i32>) -> i32 {
    value.unwrap_or(0).clamp(-720, 840)
}

fn mime_for_path(path: &std::path::Path) -> &'static str {
    match path.extension().and_then(|value| value.to_str()) {
        Some("png") => "image/png",
        Some("webp") => "image/webp",
        Some("jpg" | "jpeg") => "image/jpeg",
        _ => "application/octet-stream",
    }
}

fn spawn_reader_image_cleanup(reader_runtime_dir: PathBuf, retention_days: u16) {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(60 * 60 * 24));
        interval.tick().await;

        loop {
            interval.tick().await;
            if let Err(error) = purge_old_images(&reader_runtime_dir, OffsetDateTime::now_utc(), retention_days) {
                tracing::warn!(?error, "failed to purge old reader images");
            }
        }
    });
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        let mut signal =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).ok();
        if let Some(signal) = signal.as_mut() {
            signal.recv().await;
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
