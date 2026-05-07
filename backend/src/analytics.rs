use std::collections::BTreeMap;

use time::{Date, Duration, Month, OffsetDateTime, PrimitiveDateTime, Time};

use crate::models::{
    AlertDto, AlertSeverity, AnomalyDto, DashboardResponse, DashboardSummary, DbAnomaly, DbReading,
    ReadingDto, ReadingsPageDto, UsagePoint,
};

const LITERS_PER_CUBIC_METER: i64 = 1_000;

#[derive(Debug, Clone, Copy)]
pub enum Bucket {
    Hour,
    Day,
    Week,
    Month,
    Year,
}

impl Bucket {
    pub fn from_query(value: Option<&str>) -> Result<Self, String> {
        match value.unwrap_or("day") {
            "hour" => Ok(Self::Hour),
            "day" => Ok(Self::Day),
            "week" => Ok(Self::Week),
            "month" => Ok(Self::Month),
            "year" => Ok(Self::Year),
            other => Err(format!(
                "invalid bucket '{other}', expected hour, day, week, month, or year"
            )),
        }
    }
}

#[derive(Debug, Clone)]
struct UsageInterval {
    start: OffsetDateTime,
    end: OffsetDateTime,
    consumption_m3: i64,
    raw_delta_m3: i64,
    negative_delta: bool,
}

#[derive(Debug, Default)]
struct UsageAccumulator {
    consumption_m3: i64,
    reading_count: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReadingsPage {
    pub page: usize,
    pub page_size: usize,
    pub total_count: usize,
    pub total_pages: usize,
    pub offset: usize,
    pub limit: usize,
}

pub fn build_readings(readings: &[DbReading]) -> Vec<ReadingDto> {
    readings.iter().map(map_reading).collect()
}

pub fn build_anomalies(anomalies: &[DbAnomaly]) -> Vec<AnomalyDto> {
    anomalies.iter().map(map_anomaly).collect()
}

pub fn resolve_readings_page(
    requested_page: usize,
    page_size: usize,
    total_count: usize,
) -> ReadingsPage {
    let page_size = page_size.max(1);
    let total_pages = if total_count == 0 {
        1
    } else {
        total_count.div_ceil(page_size)
    };
    let page = requested_page.max(1).min(total_pages);
    let newer_items_skipped = (page - 1) * page_size;
    let limit = total_count
        .saturating_sub(newer_items_skipped)
        .min(page_size);
    let offset = total_count.saturating_sub(newer_items_skipped + limit);

    ReadingsPage {
        page,
        page_size,
        total_count,
        total_pages,
        offset,
        limit,
    }
}

pub fn build_readings_page(readings: &[DbReading], page: ReadingsPage) -> ReadingsPageDto {
    ReadingsPageDto {
        items: readings.iter().rev().map(map_reading).collect(),
        page: page.page,
        page_size: page.page_size,
        total_count: page.total_count,
        total_pages: page.total_pages,
    }
}

pub fn build_dashboard(
    readings: &[DbReading],
    now: OffsetDateTime,
    tz_offset_minutes: i32,
    active_alerts: usize,
    logged_anomaly_count: usize,
) -> DashboardResponse {
    let intervals = derive_intervals(readings);
    let today_start = start_of_local_day_utc(now, tz_offset_minutes);
    let month_start = start_of_local_month_utc(now, tz_offset_minutes);

    DashboardResponse {
        generated_at: now,
        summary: DashboardSummary {
            today_m3: sum_usage_between(&intervals, today_start, now),
            last_24h_m3: sum_usage_between(&intervals, now - Duration::hours(24), now),
            last_7d_m3: sum_usage_between(&intervals, now - Duration::days(7), now),
            month_to_date_m3: sum_usage_between(&intervals, month_start, now),
            active_alerts,
            anomaly_count: intervals
                .iter()
                .filter(|interval| interval.negative_delta)
                .count()
                + logged_anomaly_count,
        },
        latest_reading: readings.last().map(map_reading),
    }
}

pub fn build_consumption_series(
    readings: &[DbReading],
    bucket: Bucket,
    tz_offset_minutes: i32,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Vec<UsagePoint> {
    if readings.len() < 2 || from > to {
        return Vec::new();
    }

    let intervals = derive_intervals(readings);
    let mut by_bucket: BTreeMap<i64, UsageAccumulator> = BTreeMap::new();

    for interval in intervals
        .iter()
        .filter(|interval| !interval.negative_delta && interval.end >= from && interval.end <= to)
    {
        let local_start = local_bucket_start(interval.end, bucket, tz_offset_minutes);
        let bucket_start = unshift_from_local(local_start, tz_offset_minutes);
        let entry = by_bucket.entry(bucket_start.unix_timestamp()).or_default();
        entry.consumption_m3 += interval.consumption_m3;
        entry.reading_count += 1;
    }

    let mut points = Vec::new();
    let mut current = local_bucket_start(from, bucket, tz_offset_minutes);
    let last = local_bucket_start(to, bucket, tz_offset_minutes);

    while current <= last {
        let bucket_start = unshift_from_local(current, tz_offset_minutes);
        let bucket_end = unshift_from_local(next_bucket_start(current, bucket), tz_offset_minutes);
        let key = bucket_start.unix_timestamp();
        let accumulator = by_bucket.get(&key);

        points.push(UsagePoint {
            bucket_start,
            bucket_end,
            consumption_m3: accumulator
                .map(|value| value.consumption_m3)
                .unwrap_or_default(),
            reading_count: accumulator
                .map(|value| value.reading_count)
                .unwrap_or_default(),
        });

        current = next_bucket_start(current, bucket);
    }

    points
}

pub fn build_alerts(
    readings: &[DbReading],
    now: OffsetDateTime,
    tz_offset_minutes: i32,
    from: OffsetDateTime,
    to: OffsetDateTime,
) -> Vec<AlertDto> {
    let intervals = derive_intervals(readings);
    let mut alerts = Vec::new();

    for interval in intervals
        .iter()
        .filter(|interval| interval.negative_delta && interval.end >= from && interval.end <= to)
    {
        alerts.push(AlertDto {
            id: format!("negative-delta-{}", interval.end.unix_timestamp()),
            kind: "negative_delta".to_owned(),
            severity: AlertSeverity::High,
            message: "The cumulative meter value moved backwards. Treat this reading as a reset or bad data.".to_owned(),
            actual_value_m3: interval.raw_delta_m3,
            baseline_value_m3: None,
            ratio: None,
            starts_at: interval.start,
            ends_at: interval.end,
        });
    }

    let hourly_from = from.max(now - Duration::days(4));
    let hourly =
        build_consumption_series(readings, Bucket::Hour, tz_offset_minutes, hourly_from, now);
    if let Some(alert) = spike_alert(
        "hourly_spike",
        "Hourly usage",
        &hourly,
        24,
        2.5,
        LITERS_PER_CUBIC_METER,
    ) {
        alerts.push(alert);
    }

    let daily_from = from.max(now - Duration::days(35));
    let daily = build_consumption_series(readings, Bucket::Day, tz_offset_minutes, daily_from, now);
    if let Some(alert) = spike_alert(
        "daily_spike",
        "Daily usage",
        &daily,
        7,
        1.8,
        LITERS_PER_CUBIC_METER,
    ) {
        alerts.push(alert);
    }

    if let Some(alert) = overnight_leak_alert(&intervals, now, tz_offset_minutes) {
        alerts.push(alert);
    }

    alerts.sort_by(|left, right| {
        severity_rank(&right.severity)
            .cmp(&severity_rank(&left.severity))
            .then_with(|| right.ends_at.cmp(&left.ends_at))
    });
    alerts
}

fn derive_intervals(readings: &[DbReading]) -> Vec<UsageInterval> {
    readings
        .windows(2)
        .map(|pair| {
            let start = &pair[0];
            let end = &pair[1];
            let delta = end.meter_value_m3 - start.meter_value_m3;
            UsageInterval {
                start: start.recorded_at,
                end: end.recorded_at,
                consumption_m3: if delta.is_negative() { 0 } else { delta },
                raw_delta_m3: delta,
                negative_delta: delta.is_negative(),
            }
        })
        .collect()
}

fn sum_usage_between(intervals: &[UsageInterval], from: OffsetDateTime, to: OffsetDateTime) -> i64 {
    intervals
        .iter()
        .filter(|interval| !interval.negative_delta && interval.end > from && interval.end <= to)
        .map(|interval| interval.consumption_m3)
        .sum()
}

fn spike_alert(
    kind: &str,
    label: &str,
    points: &[UsagePoint],
    lookback: usize,
    ratio_threshold: f64,
    minimum_actual: i64,
) -> Option<AlertDto> {
    let latest = points.iter().rfind(|point| point.reading_count > 0)?;
    let previous: Vec<&UsagePoint> = points
        .iter()
        .filter(|point| point.bucket_end <= latest.bucket_start)
        .rev()
        .take(lookback)
        .filter(|point| point.reading_count > 0)
        .collect();

    if previous.len() < (lookback / 3).max(3) || latest.consumption_m3 < minimum_actual {
        return None;
    }

    let baseline = previous
        .iter()
        .map(|point| point.consumption_m3 as f64)
        .sum::<f64>()
        / previous.len() as f64;

    if baseline <= 0.0 {
        return Some(AlertDto {
            id: format!("{kind}-{}", latest.bucket_start.unix_timestamp()),
            kind: kind.to_owned(),
            severity: AlertSeverity::High,
            message: format!("{label} jumped above a zero baseline."),
            actual_value_m3: latest.consumption_m3,
            baseline_value_m3: Some(0),
            ratio: None,
            starts_at: latest.bucket_start,
            ends_at: latest.bucket_end,
        });
    }

    let ratio = latest.consumption_m3 as f64 / baseline;
    if ratio < ratio_threshold {
        return None;
    }

    let rounded_ratio = round_to_i64(ratio);

    Some(AlertDto {
        id: format!("{kind}-{}", latest.bucket_start.unix_timestamp()),
        kind: kind.to_owned(),
        severity: if ratio >= ratio_threshold + 1.0 {
            AlertSeverity::High
        } else {
            AlertSeverity::Medium
        },
        message: format!("{label} is {rounded_ratio}x above the recent baseline."),
        actual_value_m3: latest.consumption_m3,
        baseline_value_m3: Some(round_to_i64(baseline)),
        ratio: Some(rounded_ratio),
        starts_at: latest.bucket_start,
        ends_at: latest.bucket_end,
    })
}

fn overnight_leak_alert(
    intervals: &[UsageInterval],
    now: OffsetDateTime,
    tz_offset_minutes: i32,
) -> Option<AlertDto> {
    let window_start = now - Duration::days(4);
    let mut nightly_usage: BTreeMap<Date, i64> = BTreeMap::new();

    for interval in intervals.iter().filter(|interval| {
        !interval.negative_delta && interval.end >= window_start && interval.end <= now
    }) {
        let local_end = shift_to_local(interval.end, tz_offset_minutes);
        if local_end.hour() < 5 {
            *nightly_usage.entry(local_end.date()).or_default() += interval.consumption_m3;
        }
    }

    let recent_nights: Vec<(Date, i64)> = nightly_usage
        .iter()
        .rev()
        .take(3)
        .map(|(date, total)| (*date, *total))
        .collect();
    if recent_nights.len() < 2 {
        return None;
    }

    let average = recent_nights
        .iter()
        .map(|(_, total)| *total as f64)
        .sum::<f64>()
        / recent_nights.len() as f64;
    let all_nonzero = recent_nights
        .iter()
        .all(|(_, total)| *total >= LITERS_PER_CUBIC_METER);
    if !all_nonzero || average < LITERS_PER_CUBIC_METER as f64 {
        return None;
    }

    let starts_at = unshift_from_local(
        PrimitiveDateTime::new(recent_nights.last()?.0, Time::MIDNIGHT),
        tz_offset_minutes,
    );
    let ends_at = unshift_from_local(
        PrimitiveDateTime::new(recent_nights.first()?.0, Time::MIDNIGHT) + Duration::days(1),
        tz_offset_minutes,
    );

    Some(AlertDto {
        id: format!("overnight-leak-{}", ends_at.unix_timestamp()),
        kind: "overnight_leak".to_owned(),
        severity: AlertSeverity::Medium,
        message:
            "Repeated overnight flow suggests a possible leak or a fixture that never fully closes."
                .to_owned(),
        actual_value_m3: round_to_i64(average),
        baseline_value_m3: Some(LITERS_PER_CUBIC_METER),
        ratio: Some(round_to_i64(average / LITERS_PER_CUBIC_METER as f64)),
        starts_at,
        ends_at,
    })
}

fn map_reading(reading: &DbReading) -> ReadingDto {
    ReadingDto {
        id: reading.id,
        recorded_at: reading.recorded_at,
        meter_value_m3: reading.meter_value_m3,
        delta_m3: reading.delta_m3,
        source: reading.source.clone(),
    }
}

fn map_anomaly(anomaly: &DbAnomaly) -> AnomalyDto {
    AnomalyDto {
        id: anomaly.id,
        recorded_at: anomaly.recorded_at,
        meter_value_m3: anomaly.meter_value_m3,
        previous_recorded_at: anomaly.previous_recorded_at,
        previous_meter_value_m3: anomaly.previous_meter_value_m3,
        delta_m3: anomaly.delta_m3,
        threshold_m3: anomaly.threshold_m3,
        source: anomaly.source.clone(),
        image_url: anomaly
            .image_path
            .as_ref()
            .map(|path| format!("/api/reader/images/anomaly/{path}")),
        archived: anomaly.archived_at.is_some(),
        created_at: anomaly.created_at,
    }
}

fn shift_to_local(timestamp: OffsetDateTime, tz_offset_minutes: i32) -> OffsetDateTime {
    timestamp + Duration::minutes(i64::from(tz_offset_minutes))
}

fn unshift_from_local(local: PrimitiveDateTime, tz_offset_minutes: i32) -> OffsetDateTime {
    local.assume_utc() - Duration::minutes(i64::from(tz_offset_minutes))
}

fn start_of_local_day_utc(reference: OffsetDateTime, tz_offset_minutes: i32) -> OffsetDateTime {
    let local = shift_to_local(reference, tz_offset_minutes);
    let local_start = PrimitiveDateTime::new(local.date(), Time::MIDNIGHT);
    unshift_from_local(local_start, tz_offset_minutes)
}

fn start_of_local_month_utc(reference: OffsetDateTime, tz_offset_minutes: i32) -> OffsetDateTime {
    let local = shift_to_local(reference, tz_offset_minutes);
    let date = Date::from_calendar_date(local.year(), local.month(), 1).expect("valid month");
    let local_start = PrimitiveDateTime::new(date, Time::MIDNIGHT);
    unshift_from_local(local_start, tz_offset_minutes)
}

fn local_bucket_start(
    timestamp: OffsetDateTime,
    bucket: Bucket,
    tz_offset_minutes: i32,
) -> PrimitiveDateTime {
    let local = shift_to_local(timestamp, tz_offset_minutes);
    let date = local.date();
    let time = local.time();

    match bucket {
        Bucket::Hour => {
            PrimitiveDateTime::new(date, Time::from_hms(time.hour(), 0, 0).expect("valid time"))
        }
        Bucket::Day => PrimitiveDateTime::new(date, Time::MIDNIGHT),
        Bucket::Week => {
            let start_date = date - Duration::days(date.weekday().number_days_from_monday().into());
            PrimitiveDateTime::new(start_date, Time::MIDNIGHT)
        }
        Bucket::Month => {
            let start_date =
                Date::from_calendar_date(date.year(), date.month(), 1).expect("valid month");
            PrimitiveDateTime::new(start_date, Time::MIDNIGHT)
        }
        Bucket::Year => {
            let start_date =
                Date::from_calendar_date(date.year(), Month::January, 1).expect("valid year");
            PrimitiveDateTime::new(start_date, Time::MIDNIGHT)
        }
    }
}

fn next_bucket_start(start: PrimitiveDateTime, bucket: Bucket) -> PrimitiveDateTime {
    match bucket {
        Bucket::Hour => start + Duration::hours(1),
        Bucket::Day => start + Duration::days(1),
        Bucket::Week => start + Duration::days(7),
        Bucket::Month => {
            let next_month = match start.month() {
                Month::December => Date::from_calendar_date(start.year() + 1, Month::January, 1)
                    .expect("valid next month"),
                month => Date::from_calendar_date(start.year(), month.next(), 1)
                    .expect("valid next month"),
            };
            PrimitiveDateTime::new(next_month, Time::MIDNIGHT)
        }
        Bucket::Year => PrimitiveDateTime::new(
            Date::from_calendar_date(start.year() + 1, Month::January, 1).expect("valid year"),
            Time::MIDNIGHT,
        ),
    }
}

fn severity_rank(value: &AlertSeverity) -> u8 {
    match value {
        AlertSeverity::High => 3,
        AlertSeverity::Medium => 2,
        AlertSeverity::Info => 1,
    }
}

fn round_to_i64(value: f64) -> i64 {
    value.round() as i64
}

#[cfg(test)]
mod tests {
    use time::macros::datetime;

    use super::*;

    fn reading(recorded_at: OffsetDateTime, meter_value_m3: i64) -> DbReading {
        DbReading {
            id: recorded_at.unix_timestamp(),
            recorded_at,
            meter_value_m3,
            delta_m3: None,
            source: "test".to_owned(),
        }
    }

    fn reading_with_delta(
        recorded_at: OffsetDateTime,
        meter_value_m3: i64,
        delta_m3: Option<i64>,
    ) -> DbReading {
        DbReading {
            id: recorded_at.unix_timestamp(),
            recorded_at,
            meter_value_m3,
            delta_m3,
            source: "test".to_owned(),
        }
    }

    #[test]
    fn readings_page_clamps_to_last_page_and_returns_newest_first() {
        let readings = vec![
            reading(datetime!(2026-04-01 00:00 UTC), 10),
            reading(datetime!(2026-04-01 01:00 UTC), 12),
        ];

        let page = resolve_readings_page(3, 2, 2);
        let response = build_readings_page(&readings, page);

        assert_eq!(page.page, 1);
        assert_eq!(page.total_pages, 1);
        assert_eq!(page.offset, 0);
        assert_eq!(page.limit, 2);
        assert_eq!(response.total_count, 2);
        assert_eq!(
            response.items[0].id,
            datetime!(2026-04-01 01:00 UTC).unix_timestamp()
        );
        assert_eq!(
            response.items[1].id,
            datetime!(2026-04-01 00:00 UTC).unix_timestamp()
        );
    }

    #[test]
    fn readings_page_uses_descending_pagination_offsets() {
        let readings = vec![
            reading(datetime!(2026-04-01 00:00 UTC), 10),
            reading(datetime!(2026-04-01 01:00 UTC), 12),
            reading(datetime!(2026-04-01 02:00 UTC), 14),
        ];

        let first_page = resolve_readings_page(1, 2, readings.len());
        let first_page_response = build_readings_page(
            &readings[first_page.offset..first_page.offset + first_page.limit],
            first_page,
        );

        assert_eq!(first_page.offset, 1);
        assert_eq!(first_page.limit, 2);
        assert_eq!(
            first_page_response
                .items
                .iter()
                .map(|reading| reading.id)
                .collect::<Vec<_>>(),
            vec![
                datetime!(2026-04-01 02:00 UTC).unix_timestamp(),
                datetime!(2026-04-01 01:00 UTC).unix_timestamp(),
            ]
        );

        let last_page = resolve_readings_page(2, 2, readings.len());
        let last_page_response = build_readings_page(
            &readings[last_page.offset..last_page.offset + last_page.limit],
            last_page,
        );

        assert_eq!(last_page.offset, 0);
        assert_eq!(last_page.limit, 1);
        assert_eq!(
            last_page_response
                .items
                .iter()
                .map(|reading| reading.id)
                .collect::<Vec<_>>(),
            vec![datetime!(2026-04-01 00:00 UTC).unix_timestamp()]
        );
    }

    #[test]
    fn readings_page_includes_delta_from_previous_row() {
        let readings = vec![
            reading_with_delta(datetime!(2026-04-01 01:00 UTC), 10_350, Some(350)),
            reading_with_delta(datetime!(2026-04-01 02:00 UTC), 11_000, Some(650)),
        ];

        let response = build_readings_page(
            &readings,
            ReadingsPage {
                page: 1,
                page_size: 2,
                total_count: 3,
                total_pages: 2,
                offset: 1,
                limit: 2,
            },
        );

        assert_eq!(response.items.len(), 2);
        assert_eq!(response.items[0].meter_value_m3, 11_000);
        assert_eq!(response.items[0].delta_m3, Some(650));
        assert_eq!(response.items[1].meter_value_m3, 10_350);
        assert_eq!(response.items[1].delta_m3, Some(350));
    }

    #[test]
    fn readings_page_leaves_oldest_row_without_delta() {
        let response = build_readings_page(
            &[reading_with_delta(
                datetime!(2026-04-01 00:00 UTC),
                10_000,
                None,
            )],
            ReadingsPage {
                page: 2,
                page_size: 2,
                total_count: 3,
                total_pages: 2,
                offset: 0,
                limit: 1,
            },
        );

        assert_eq!(response.items.len(), 1);
        assert_eq!(response.items[0].meter_value_m3, 10_000);
        assert_eq!(response.items[0].delta_m3, None);
    }

    #[test]
    fn dashboard_summary_uses_positive_deltas_only() {
        let readings = vec![
            reading(datetime!(2026-04-01 00:00 UTC), 10_000),
            reading(datetime!(2026-04-01 06:00 UTC), 12_000),
            reading(datetime!(2026-04-01 12:00 UTC), 11_000),
            reading(datetime!(2026-04-01 18:00 UTC), 15_000),
            reading(datetime!(2026-04-02 01:00 UTC), 18_000),
        ];

        let summary = build_dashboard(&readings, datetime!(2026-04-02 03:00 UTC), 0, 2, 0).summary;

        assert_eq!(summary.today_m3, 3_000);
        assert_eq!(summary.last_24h_m3, 9_000);
        assert_eq!(summary.month_to_date_m3, 9_000);
        assert_eq!(summary.active_alerts, 2);
        assert_eq!(summary.anomaly_count, 1);
    }

    #[test]
    fn consumption_series_zero_fills_missing_buckets() {
        let readings = vec![
            reading(datetime!(2026-04-10 00:00 UTC), 11_000),
            reading(datetime!(2026-04-10 01:00 UTC), 12_000),
            reading(datetime!(2026-04-10 02:00 UTC), 15_000),
            reading(datetime!(2026-04-10 04:00 UTC), 17_000),
        ];

        let series = build_consumption_series(
            &readings,
            Bucket::Hour,
            0,
            datetime!(2026-04-10 00:30 UTC),
            datetime!(2026-04-10 04:30 UTC),
        );

        let consumption: Vec<i64> = series.iter().map(|point| point.consumption_m3).collect();
        assert_eq!(consumption, vec![0, 1_000, 3_000, 0, 2_000]);
    }

    #[test]
    fn alerts_include_negative_delta_reset_signal() {
        let readings = vec![
            reading(datetime!(2026-04-12 00:00 UTC), 20_000),
            reading(datetime!(2026-04-12 01:00 UTC), 22_000),
            reading(datetime!(2026-04-12 02:00 UTC), 19_000),
            reading(datetime!(2026-04-12 03:00 UTC), 21_000),
        ];

        let alerts = build_alerts(
            &readings,
            datetime!(2026-04-12 03:30 UTC),
            0,
            datetime!(2026-04-12 00:00 UTC),
            datetime!(2026-04-12 03:30 UTC),
        );

        assert!(alerts.iter().any(|alert| alert.kind == "negative_delta"));
    }

    #[test]
    fn readings_keep_liter_precision_in_responses() {
        let readings = vec![reading(datetime!(2026-04-01 00:00 UTC), 891_120)];

        let response = build_readings(&readings);

        assert_eq!(response[0].meter_value_m3, 891_120);
    }
}
