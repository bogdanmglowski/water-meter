export type RangePreset = "24h" | "7d" | "30d" | "90d";
export type Bucket = "hour" | "day" | "week" | "month";
export type AlertSeverity = "info" | "medium" | "high";

export interface Reading {
  recordedAt: string;
  meterValueM3: number;
  source: string;
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

