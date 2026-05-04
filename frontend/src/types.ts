export type RangePreset = "24h" | "3d" | "7d" | "30d" | "90d" | "365d";
export type Bucket = "hour" | "day" | "week" | "month" | "year";
export type AlertSeverity = "info" | "medium" | "high";

export interface Reading {
  id: number;
  recordedAt: string;
  meterValueM3: number;
  deltaM3: number | null;
  source: string;
}

export interface ReadingsPage {
  items: Reading[];
  page: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
}

export interface UsagePoint {
  bucketStart: string;
  bucketEnd: string;
  consumptionM3: number;
  readingCount: number;
}

export interface AlertItem {
  id: string;
  kind: string;
  severity: AlertSeverity;
  message: string;
  actualValueM3: number;
  baselineValueM3: number | null;
  ratio: number | null;
  startsAt: string;
  endsAt: string;
}

export interface AnomalyItem {
  id: number;
  recordedAt: string;
  meterValueM3: number;
  previousRecordedAt: string;
  previousMeterValueM3: number;
  deltaM3: number;
  thresholdM3: number;
  source: string;
  createdAt: string;
}

export interface DashboardSummary {
  todayM3: number;
  last24hM3: number;
  last7dM3: number;
  monthToDateM3: number;
  activeAlerts: number;
  anomalyCount: number;
}

export interface DashboardResponse {
  generatedAt: string;
  summary: DashboardSummary;
  latestReading: Reading | null;
}

export interface ReaderImageItem {
  kind: string;
  name: string;
  url: string;
  path: string;
  capturedAt: string;
}

export interface ReaderImageDayGroup {
  day: string;
  items: ReaderImageItem[];
}

export interface ReaderGallerySection {
  page: number;
  pageSize: number;
  totalDays: number;
  totalPages: number;
  dayGroups: ReaderImageDayGroup[];
}

export interface ReaderGallery {
  currentCropUrl: string | null;
  originalImages: ReaderGallerySection;
  processedImages: ReaderGallerySection;
}
