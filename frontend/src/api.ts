import type {
  AlertItem,
  Bucket,
  DashboardResponse,
  Reading,
  UsagePoint,
} from "./types";
import { toIsoTimestamp } from "./utils";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

type RawReading = Omit<Reading, "recordedAt"> & { recordedAt: unknown };
type RawUsagePoint = Omit<UsagePoint, "bucketStart" | "bucketEnd"> & {
  bucketStart: unknown;
  bucketEnd: unknown;
};
type RawAlertItem = Omit<AlertItem, "startsAt" | "endsAt"> & {
  startsAt: unknown;
  endsAt: unknown;
};
type RawDashboardResponse = Omit<DashboardResponse, "generatedAt" | "latestReading"> & {
  generatedAt: unknown;
  latestReading: RawReading | null;
};

interface RangeParams {
  from: string;
  to: string;
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  return url;
}

async function request<T>(path: string, params?: Record<string, string | number | undefined>) {
  const response = await fetch(buildUrl(path, params), {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

function isPresent<T>(value: T | null): value is T {
  return value !== null;
}

function normalizeReading(reading: RawReading): Reading | null {
  const recordedAt = toIsoTimestamp(reading.recordedAt);
  if (!recordedAt) {
    return null;
  }

  return {
    ...reading,
    recordedAt,
  };
}

function normalizeUsagePoint(point: RawUsagePoint): UsagePoint | null {
  const bucketStart = toIsoTimestamp(point.bucketStart);
  const bucketEnd = toIsoTimestamp(point.bucketEnd);
  if (!bucketStart || !bucketEnd) {
    return null;
  }

  return {
    ...point,
    bucketStart,
    bucketEnd,
  };
}

function normalizeAlert(alert: RawAlertItem): AlertItem | null {
  const startsAt = toIsoTimestamp(alert.startsAt);
  const endsAt = toIsoTimestamp(alert.endsAt);
  if (!startsAt || !endsAt) {
    return null;
  }

  return {
    ...alert,
    startsAt,
    endsAt,
  };
}

function normalizeDashboard(response: RawDashboardResponse): DashboardResponse {
  return {
    ...response,
    generatedAt: toIsoTimestamp(response.generatedAt) ?? "",
    latestReading: response.latestReading ? normalizeReading(response.latestReading) : null,
  };
}

export function getDashboard(tzOffsetMinutes: number) {
  return request<RawDashboardResponse>("/api/dashboard", {
    tz_offset_minutes: tzOffsetMinutes,
  }).then(normalizeDashboard);
}

export function getCumulative(range: RangeParams) {
  return request<RawReading[]>("/api/series/cumulative", { ...range }).then((rows) =>
    rows.map(normalizeReading).filter(isPresent),
  );
}

export function getConsumption(
  range: RangeParams & { bucket: Bucket; tzOffsetMinutes: number },
) {
  return request<RawUsagePoint[]>("/api/series/consumption", {
    from: range.from,
    to: range.to,
    bucket: range.bucket,
    tz_offset_minutes: range.tzOffsetMinutes,
  }).then((rows) => rows.map(normalizeUsagePoint).filter(isPresent));
}

export function getAlerts(range: RangeParams & { tzOffsetMinutes: number }) {
  return request<RawAlertItem[]>("/api/alerts", {
    from: range.from,
    to: range.to,
    tz_offset_minutes: range.tzOffsetMinutes,
  }).then((rows) => rows.map(normalizeAlert).filter(isPresent));
}

export function getReadings(range: RangeParams & { limit: number }) {
  return request<RawReading[]>("/api/readings", {
    from: range.from,
    to: range.to,
    limit: range.limit,
  }).then((rows) => rows.map(normalizeReading).filter(isPresent));
}
