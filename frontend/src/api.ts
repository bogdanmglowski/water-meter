import type {
  AlertItem,
  AnomalyItem,
  Bucket,
  DashboardResponse,
  ReaderGallery,
  ReaderGallerySection,
  ReaderImageItem,
  Reading,
  ReadingsPage,
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
type RawAnomalyItem = Omit<
  AnomalyItem,
  "recordedAt" | "previousRecordedAt" | "createdAt"
> & {
  recordedAt: unknown;
  previousRecordedAt: unknown;
  createdAt: unknown;
};
type RawDashboardResponse = Omit<DashboardResponse, "generatedAt" | "latestReading"> & {
  generatedAt: unknown;
  latestReading: RawReading | null;
};
type RawReadingsPage = Omit<ReadingsPage, "items"> & {
  items: RawReading[];
};
type RawReaderImageItem = ReaderImageItem;
type RawReaderGallerySection = ReaderGallerySection;
type RawReaderGallery = Omit<ReaderGallery, "currentCropUrl" | "originalImages" | "processedImages"> & {
  currentCropUrl: string | null;
  originalImages: RawReaderGallerySection;
  processedImages: RawReaderGallerySection;
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

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  init?: RequestInit,
) {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(buildUrl(path, params), {
    ...init,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;

    try {
      const contentType = response.headers.get("content-type") ?? "";
      if (contentType.includes("application/json")) {
        const body = (await response.json()) as { error?: unknown };
        if (typeof body.error === "string" && body.error.trim()) {
          message = body.error;
        }
      } else {
        const text = await response.text();
        if (text.trim()) {
          message = text;
        }
      }
    } catch {
      // Fall back to the default status message.
    }

    throw new Error(message);
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

function normalizeAnomaly(anomaly: RawAnomalyItem): AnomalyItem | null {
  const recordedAt = toIsoTimestamp(anomaly.recordedAt);
  const previousRecordedAt = toIsoTimestamp(anomaly.previousRecordedAt);
  const createdAt = toIsoTimestamp(anomaly.createdAt);
  if (!recordedAt || !previousRecordedAt || !createdAt) {
    return null;
  }

  return {
    ...anomaly,
    recordedAt,
    previousRecordedAt,
    createdAt,
  };
}

function normalizeDashboard(response: RawDashboardResponse): DashboardResponse {
  return {
    ...response,
    generatedAt: toIsoTimestamp(response.generatedAt) ?? "",
    latestReading: response.latestReading ? normalizeReading(response.latestReading) : null,
  };
}

function normalizeReadingsPage(response: RawReadingsPage): ReadingsPage {
  return {
    ...response,
    items: response.items.map(normalizeReading).filter(isPresent),
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

export function getAnomalies(range: RangeParams) {
  return request<RawAnomalyItem[]>("/api/anomalies", {
    from: range.from,
    to: range.to,
  }).then((rows) => rows.map(normalizeAnomaly).filter(isPresent));
}

export function getReadings(range: RangeParams & { page: number; pageSize: number }) {
  return request<RawReadingsPage>("/api/readings", {
    from: range.from,
    to: range.to,
    page: range.page,
    page_size: range.pageSize,
  }).then(normalizeReadingsPage);
}

export function deleteReading(id: number) {
  return request<{ deleted: boolean; id: number }>(`/api/readings/${id}`, undefined, {
    method: "DELETE",
  });
}

export function getReaderGallery() {
  return request<RawReaderGallery>("/api/reader/gallery", {
    original_page: 1,
    processed_page: 1,
    page_size: 7,
  }).then((gallery) => ({
    currentCropUrl: gallery.currentCropUrl,
    originalImages: gallery.originalImages,
    processedImages: gallery.processedImages,
  }));
}

export function getReaderGalleryPage(params: {
  originalPage: number;
  processedPage: number;
  pageSize: number;
}) {
  return request<RawReaderGallery>("/api/reader/gallery", {
    original_page: params.originalPage,
    processed_page: params.processedPage,
    page_size: params.pageSize,
  }).then((gallery) => ({
    currentCropUrl: gallery.currentCropUrl,
    originalImages: gallery.originalImages,
    processedImages: gallery.processedImages,
  }));
}
