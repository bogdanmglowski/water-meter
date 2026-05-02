use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use time::OffsetDateTime;
use utoipa::ToSchema;

#[derive(Debug, Clone, FromRow)]
pub struct DbReading {
    pub id: i64,
    pub recorded_at: OffsetDateTime,
    pub meter_value_m3: i64,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct HealthResponse {
    pub status: String,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub timestamp: OffsetDateTime,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct ReadingDto {
    pub id: i64,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub recorded_at: OffsetDateTime,
    pub meter_value_m3: i64,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct ReadingsPageDto {
    pub items: Vec<ReadingDto>,
    pub page: usize,
    pub page_size: usize,
    pub total_count: usize,
    pub total_pages: usize,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct DeleteReadingResponse {
    pub deleted: bool,
    pub id: i64,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct UsagePoint {
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub bucket_start: OffsetDateTime,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub bucket_end: OffsetDateTime,
    pub consumption_m3: i64,
    pub reading_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum AlertSeverity {
    Info,
    Medium,
    High,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct AlertDto {
    pub id: String,
    pub kind: String,
    pub severity: AlertSeverity,
    pub message: String,
    pub actual_value_m3: i64,
    pub baseline_value_m3: Option<i64>,
    pub ratio: Option<i64>,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub starts_at: OffsetDateTime,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub ends_at: OffsetDateTime,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct DashboardSummary {
    pub today_m3: i64,
    pub last_24h_m3: i64,
    pub last_7d_m3: i64,
    pub month_to_date_m3: i64,
    pub active_alerts: usize,
    pub anomaly_count: usize,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct DashboardResponse {
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub generated_at: OffsetDateTime,
    pub summary: DashboardSummary,
    pub latest_reading: Option<ReadingDto>,
}

#[derive(Debug, Deserialize)]
pub struct DashboardQuery {
    pub tz_offset_minutes: Option<i32>,
}

#[derive(Debug, Deserialize)]
pub struct RangeQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub tz_offset_minutes: Option<i32>,
}

#[derive(Debug, Deserialize)]
pub struct ReadingsQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub page: Option<usize>,
    pub page_size: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub struct ConsumptionQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub bucket: Option<String>,
    pub tz_offset_minutes: Option<i32>,
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use time::macros::datetime;

    use super::{
        AlertDto, AlertSeverity, DashboardResponse, DashboardSummary, ReadingDto, UsagePoint,
    };

    #[test]
    fn dto_timestamps_serialize_as_rfc3339_strings() {
        let response = DashboardResponse {
            generated_at: datetime!(2026-04-26 10:11:12 UTC),
            summary: DashboardSummary {
                today_m3: 3,
                last_24h_m3: 12,
                last_7d_m3: 57,
                month_to_date_m3: 91,
                active_alerts: 2,
                anomaly_count: 1,
            },
            latest_reading: Some(ReadingDto {
                id: 7,
                recorded_at: datetime!(2026-04-26 09:08:07 UTC),
                meter_value_m3: 43,
                source: "seed".to_owned(),
            }),
        };

        let point = UsagePoint {
            bucket_start: datetime!(2026-04-20 00:00 UTC),
            bucket_end: datetime!(2026-04-21 00:00 UTC),
            consumption_m3: 5,
            reading_count: 3,
        };

        let alert = AlertDto {
            id: "hourly-spike".to_owned(),
            kind: "hourly_spike".to_owned(),
            severity: AlertSeverity::High,
            message: "usage spiked".to_owned(),
            actual_value_m3: 7,
            baseline_value_m3: Some(2),
            ratio: Some(3),
            starts_at: datetime!(2026-04-25 22:00 UTC),
            ends_at: datetime!(2026-04-25 23:00 UTC),
        };

        let response_json = serde_json::to_value(response).expect("dashboard serializes");
        let point_json = serde_json::to_value(point).expect("usage point serializes");
        let alert_json = serde_json::to_value(alert).expect("alert serializes");

        assert_eq!(response_json["generatedAt"], json!("2026-04-26T10:11:12Z"));
        assert_eq!(response_json["latestReading"]["id"], json!(7));
        assert_eq!(
            response_json["latestReading"]["recordedAt"],
            json!("2026-04-26T09:08:07Z")
        );
        assert_eq!(point_json["bucketStart"], json!("2026-04-20T00:00:00Z"));
        assert_eq!(point_json["bucketEnd"], json!("2026-04-21T00:00:00Z"));
        assert_eq!(alert_json["startsAt"], json!("2026-04-25T22:00:00Z"));
        assert_eq!(alert_json["endsAt"], json!("2026-04-25T23:00:00Z"));
    }
}
