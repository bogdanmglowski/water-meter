use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use time::OffsetDateTime;
use utoipa::ToSchema;

#[derive(Debug, Clone, FromRow)]
pub struct DbReading {
    pub id: i64,
    pub recorded_at: OffsetDateTime,
    pub meter_value_m3: i64,
    pub delta_m3: Option<i64>,
    pub source: String,
}

#[derive(Debug, Clone, FromRow)]
pub struct DbAnomaly {
    pub id: i64,
    pub recorded_at: OffsetDateTime,
    pub meter_value_m3: i64,
    pub previous_recorded_at: OffsetDateTime,
    pub previous_meter_value_m3: i64,
    pub delta_m3: i64,
    pub threshold_m3: i64,
    pub source: String,
    pub image_path: Option<String>,
    pub archived_at: Option<OffsetDateTime>,
    pub created_at: OffsetDateTime,
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
    pub delta_m3: Option<i64>,
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
pub struct DeleteReaderImageResponse {
    pub deleted: bool,
    pub category: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct AnomalyDto {
    pub id: i64,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub recorded_at: OffsetDateTime,
    pub meter_value_m3: i64,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub previous_recorded_at: OffsetDateTime,
    pub previous_meter_value_m3: i64,
    pub delta_m3: i64,
    pub threshold_m3: i64,
    pub source: String,
    pub image_url: Option<String>,
    pub archived: bool,
    #[serde(with = "time::serde::rfc3339")]
    #[schema(value_type = String, format = DateTime)]
    pub created_at: OffsetDateTime,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct ArchiveAnomalyResponse {
    pub id: i64,
    pub archived: bool,
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
pub struct AnomaliesQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub include_archived: Option<bool>,
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

#[derive(Debug, Clone, Serialize, ToSchema, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ReaderImageItem {
    pub kind: String,
    pub name: String,
    pub url: String,
    pub path: String,
    pub captured_at: String,
}

#[derive(Debug, Clone, Serialize, ToSchema, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ReaderImageDayGroup {
    pub day: String,
    pub items: Vec<ReaderImageItem>,
}

#[derive(Debug, Clone, Serialize, ToSchema, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ReaderGallerySection {
    pub page: usize,
    pub page_size: usize,
    pub total_days: usize,
    pub total_pages: usize,
    pub day_groups: Vec<ReaderImageDayGroup>,
}

#[derive(Debug, Deserialize)]
pub struct ReaderGalleryQuery {
    pub original_page: Option<usize>,
    pub processed_page: Option<usize>,
    pub page_size: Option<usize>,
}

#[derive(Debug, Clone, Serialize, ToSchema, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ReaderGalleryResponse {
    pub current_crop_url: Option<String>,
    pub original_images: ReaderGallerySection,
    pub processed_images: ReaderGallerySection,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct ManualReadResponse {
    pub recorded_at: String,
    pub meter_value_m3: i64,
    pub image_path: String,
    pub crop_path: String,
}

#[derive(Debug, Deserialize)]
pub struct ReaderManualReadPayload {
    pub recorded_at: String,
    pub meter_value_m3: i64,
    pub image_path: String,
    pub crop_path: String,
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use time::macros::datetime;

    use super::{
        AlertDto, AlertSeverity, AnomalyDto, ArchiveAnomalyResponse, DashboardResponse,
        DashboardSummary, ManualReadResponse, ReaderGalleryResponse, ReaderGallerySection,
        ReaderImageDayGroup, ReaderImageItem, ReadingDto, UsagePoint,
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
                delta_m3: Some(3),
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

        let anomaly = AnomalyDto {
            id: 12,
            recorded_at: datetime!(2026-04-26 09:08:07 UTC),
            meter_value_m3: 1600,
            previous_recorded_at: datetime!(2026-04-26 09:03:07 UTC),
            previous_meter_value_m3: 1450,
            delta_m3: 150,
            threshold_m3: 100,
            source: "reader".to_owned(),
            image_url: Some(
                "/api/reader/images/anomaly/2026-04-26/2026-04-26_09-08-07_anomaly-12.png"
                    .to_owned(),
            ),
            archived: true,
            created_at: datetime!(2026-04-26 09:08:08 UTC),
        };
        let archive_response = ArchiveAnomalyResponse {
            id: 12,
            archived: true,
        };

        let response_json = serde_json::to_value(response).expect("dashboard serializes");
        let point_json = serde_json::to_value(point).expect("usage point serializes");
        let alert_json = serde_json::to_value(alert).expect("alert serializes");
        let anomaly_json = serde_json::to_value(anomaly).expect("anomaly serializes");
        let archive_response_json =
            serde_json::to_value(archive_response).expect("archive response serializes");

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
        assert_eq!(anomaly_json["recordedAt"], json!("2026-04-26T09:08:07Z"));
        assert_eq!(
            anomaly_json["previousRecordedAt"],
            json!("2026-04-26T09:03:07Z")
        );
        assert_eq!(
            anomaly_json["imageUrl"],
            json!("/api/reader/images/anomaly/2026-04-26/2026-04-26_09-08-07_anomaly-12.png")
        );
        assert_eq!(anomaly_json["archived"], json!(true));
        assert_eq!(anomaly_json["createdAt"], json!("2026-04-26T09:08:08Z"));
        assert_eq!(archive_response_json["id"], json!(12));
        assert_eq!(archive_response_json["archived"], json!(true));
    }

    #[test]
    fn reader_gallery_serializes_in_camel_case() {
        let gallery = ReaderGalleryResponse {
            current_crop_url: Some("/api/reader/images/current/meter-crop.png".to_owned()),
            original_images: ReaderGallerySection {
                page: 1,
                page_size: 7,
                total_days: 1,
                total_pages: 1,
                day_groups: vec![ReaderImageDayGroup {
                    day: "2026-03-16".to_owned(),
                    items: vec![ReaderImageItem {
                        kind: "original".to_owned(),
                        name: "2026-03-16_10-20-50.jpg".to_owned(),
                        url: "/api/reader/images/original/2026-03-16/2026-03-16_10-20-50.jpg"
                            .to_owned(),
                        path: "2026-03-16/2026-03-16_10-20-50.jpg".to_owned(),
                        captured_at: "2026-03-16T10:20:50Z".to_owned(),
                    }],
                }],
            },
            processed_images: ReaderGallerySection {
                page: 1,
                page_size: 7,
                total_days: 0,
                total_pages: 1,
                day_groups: vec![],
            },
        };

        let gallery_json = serde_json::to_value(gallery).expect("gallery serializes");

        assert_eq!(
            gallery_json["currentCropUrl"],
            json!("/api/reader/images/current/meter-crop.png")
        );
        assert_eq!(gallery_json["originalImages"]["pageSize"], json!(7));
        assert_eq!(
            gallery_json["originalImages"]["dayGroups"][0]["day"],
            json!("2026-03-16")
        );
        assert_eq!(
            gallery_json["originalImages"]["dayGroups"][0]["items"][0]["path"],
            json!("2026-03-16/2026-03-16_10-20-50.jpg")
        );
        assert_eq!(
            gallery_json["originalImages"]["dayGroups"][0]["items"][0]["capturedAt"],
            json!("2026-03-16T10:20:50Z")
        );
        assert_eq!(gallery_json["processedImages"]["dayGroups"], json!([]));
    }

    #[test]
    fn manual_read_response_serializes_in_camel_case() {
        let response = ManualReadResponse {
            recorded_at: "2026-03-16T10:20:50Z".to_owned(),
            meter_value_m3: 12345,
            image_path: "2026-03-16/2026-03-16_10-20-50.jpg".to_owned(),
            crop_path: "2026-03-16/2026-03-16_10-20-50.jpg".to_owned(),
        };

        let response_json = serde_json::to_value(response).expect("manual read serializes");

        assert_eq!(response_json["recordedAt"], json!("2026-03-16T10:20:50Z"));
        assert_eq!(response_json["meterValueM3"], json!(12345));
        assert_eq!(
            response_json["imagePath"],
            json!("2026-03-16/2026-03-16_10-20-50.jpg")
        );
        assert_eq!(
            response_json["cropPath"],
            json!("2026-03-16/2026-03-16_10-20-50.jpg")
        );
    }

}
