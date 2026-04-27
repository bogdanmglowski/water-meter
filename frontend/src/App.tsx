import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getAlerts, getConsumption, getCumulative, getDashboard, getReadings } from "./api";
import { AlertPanel } from "./components/AlertPanel";
import { ChartCard } from "./components/ChartCard";
import { EChart, type WaterMeterChartOption } from "./components/EChart";
import { MetricCard } from "./components/MetricCard";
import { ReadingsTable } from "./components/ReadingsTable";
import type { Bucket, RangePreset } from "./types";
import {
  buildRange,
  formatBucketLabel,
  formatTimestamp,
  formatVolume,
  rollingAverage,
} from "./utils";

const presets: RangePreset[] = ["24h", "7d", "30d", "90d"];
const buckets: Bucket[] = ["hour", "day", "week", "month"];

export default function App() {
  const [preset, setPreset] = useState<RangePreset>("30d");
  const [bucket, setBucket] = useState<Bucket>("day");

  const tzOffsetMinutes = -new Date().getTimezoneOffset();
  const activeRange = buildRange(preset);
  const baselineRange = buildRange("30d");

  const dashboardQuery = useQuery({
    queryKey: ["dashboard", tzOffsetMinutes],
    queryFn: () => getDashboard(tzOffsetMinutes),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const cumulativeQuery = useQuery({
    queryKey: ["cumulative", activeRange.from, activeRange.to],
    queryFn: () => getCumulative(activeRange),
    staleTime: 60_000,
  });

  const consumptionQuery = useQuery({
    queryKey: ["consumption", activeRange.from, activeRange.to, bucket, tzOffsetMinutes],
    queryFn: () =>
      getConsumption({
        ...activeRange,
        bucket,
        tzOffsetMinutes,
      }),
    staleTime: 60_000,
  });

  const baselineQuery = useQuery({
    queryKey: ["baseline", baselineRange.from, baselineRange.to, tzOffsetMinutes],
    queryFn: () =>
      getConsumption({
        ...baselineRange,
        bucket: "day",
        tzOffsetMinutes,
      }),
    staleTime: 60_000,
  });

  const alertsQuery = useQuery({
    queryKey: ["alerts", activeRange.from, activeRange.to, tzOffsetMinutes],
    queryFn: () =>
      getAlerts({
        ...activeRange,
        tzOffsetMinutes,
      }),
    staleTime: 60_000,
  });

  const readingsQuery = useQuery({
    queryKey: ["readings", activeRange.from, activeRange.to],
    queryFn: () =>
      getReadings({
        ...activeRange,
        limit: 160,
      }),
    staleTime: 60_000,
  });

  const error =
    dashboardQuery.error ||
    cumulativeQuery.error ||
    consumptionQuery.error ||
    baselineQuery.error ||
    alertsQuery.error ||
    readingsQuery.error;

  const dailySeries = baselineQuery.data ?? [];
  const dailyBaseline = rollingAverage(dailySeries, 7);

  const cumulativeOption: WaterMeterChartOption = {
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 20, top: 24, bottom: 40 },
    xAxis: { type: "time" },
    yAxis: {
      type: "value",
      name: "m³",
      splitLine: { lineStyle: { color: "rgba(15, 93, 74, 0.15)" } },
    },
    series: [
      {
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: "#0f5d4a" },
        areaStyle: {
          color: "rgba(15, 93, 74, 0.14)",
        },
        data: (cumulativeQuery.data ?? []).map((point) => [
          point.recordedAt,
          point.meterValueM3,
        ]),
      },
    ],
  };

  const consumptionOption: WaterMeterChartOption = {
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 20, top: 24, bottom: 56 },
    xAxis: {
      type: "category",
      axisLabel: { rotate: 30 },
      data: (consumptionQuery.data ?? []).map((point) =>
        formatBucketLabel(point.bucketStart, point.bucketEnd),
      ),
    },
    yAxis: {
      type: "value",
      name: "m³",
      splitLine: { lineStyle: { color: "rgba(133, 87, 35, 0.14)" } },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 28,
        itemStyle: {
          color: "#c8752f",
          borderRadius: [8, 8, 2, 2],
        },
        data: (consumptionQuery.data ?? []).map((point) => point.consumptionM3),
      },
    ],
  };

  const baselineOption: WaterMeterChartOption = {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 48, right: 20, top: 48, bottom: 56 },
    xAxis: {
      type: "category",
      axisLabel: { rotate: 30 },
      data: dailySeries.map((point) => formatBucketLabel(point.bucketStart, point.bucketEnd)),
    },
    yAxis: {
      type: "value",
      name: "m³",
      splitLine: { lineStyle: { color: "rgba(44, 73, 115, 0.14)" } },
    },
    series: [
      {
        name: "Actual",
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: "#244973" },
        areaStyle: { color: "rgba(36, 73, 115, 0.12)" },
        data: dailySeries.map((point) => point.consumptionM3),
      },
      {
        name: "7-day average",
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, type: "dashed", color: "#7ea3c7" },
        data: dailyBaseline,
      },
    ],
  };

  return (
    <main className="page-shell">
      <div className="page-bg" />
      <div className="page">
        <header className="topbar">
          <div>
            <span className="eyebrow">Self-hosted analytics</span>
            <h1>Water Meter</h1>
            <p>
              Consumption trends, leak hints, and raw cumulative readings from a
              single PostgreSQL-backed meter feed.
            </p>
          </div>
          <div className="status-panel">
            <span className="status-chip">Read only</span>
            <span className="status-panel__text">
              {dashboardQuery.data?.generatedAt
                ? `Updated ${formatTimestamp(dashboardQuery.data.generatedAt)}`
                : "Waiting for data"}
            </span>
          </div>
        </header>

        <section className="hero-grid">
          <div className="hero-card card">
            <div className="hero-card__copy">
              <span className="eyebrow">Current meter state</span>
              <strong className="hero-card__value">
                {dashboardQuery.data?.latestReading
                  ? formatVolume(dashboardQuery.data.latestReading.meterValueM3)
                  : "No reading"}
              </strong>
              <p>
                {dashboardQuery.data?.latestReading
                  ? `Latest sample at ${formatTimestamp(
                      dashboardQuery.data.latestReading.recordedAt,
                    )}`
                  : "Seed the database or connect your external reader."}
              </p>
            </div>
            <div className="hero-card__summary">
              <span className="label">Recent anomalies</span>
              <strong>
                {dashboardQuery.data?.summary.anomalyCount ?? 0}
              </strong>
              <span className="label">Active alerts</span>
              <strong>{dashboardQuery.data?.summary.activeAlerts ?? 0}</strong>
            </div>
          </div>

          <div className="control-card card">
            <div className="section-head">
              <div>
                <h2>Range</h2>
                <p>Switch time windows without leaving the dashboard.</p>
              </div>
            </div>
            <div className="segmented">
              {presets.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={item === preset ? "is-active" : ""}
                  onClick={() => setPreset(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="section-head section-head--compact">
              <div>
                <h2>Bucket</h2>
                <p>Choose how interval consumption is grouped.</p>
              </div>
            </div>
            <div className="segmented segmented--compact">
              {buckets.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={item === bucket ? "is-active" : ""}
                  onClick={() => setBucket(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        </section>

        {error ? (
          <section className="card error-card">
            <strong>API request failed.</strong>
            <p>{error.message}</p>
          </section>
        ) : null}

        <section className="metric-grid">
          <MetricCard
            label="Today"
            value={formatVolume(dashboardQuery.data?.summary.todayM3 ?? 0)}
            detail="Local-day consumption derived from cumulative deltas."
            tone="accent"
          />
          <MetricCard
            label="Last 24 hours"
            value={formatVolume(dashboardQuery.data?.summary.last24hM3 ?? 0)}
            detail="Rolling day view for recent usage bursts."
          />
          <MetricCard
            label="Last 7 days"
            value={formatVolume(dashboardQuery.data?.summary.last7dM3 ?? 0)}
            detail="Useful for short-term household pattern changes."
          />
          <MetricCard
            label="Month to date"
            value={formatVolume(dashboardQuery.data?.summary.monthToDateM3 ?? 0)}
            detail="Current month accumulation in the browser's timezone."
            tone="warning"
          />
        </section>

        <section className="grid-two">
          <ChartCard
            title="Cumulative Meter Trend"
            subtitle="Raw cumulative readings show how the register moves over time."
          >
            <EChart option={cumulativeOption} height={340} />
          </ChartCard>

          <AlertPanel alerts={alertsQuery.data ?? []} />
        </section>

        <section className="grid-two">
          <ChartCard
            title="Interval Consumption"
            subtitle={`Usage grouped by ${bucket}. Zero-filled buckets expose quiet periods clearly.`}
          >
            <EChart option={consumptionOption} height={320} />
          </ChartCard>

          <ChartCard
            title="Daily Baseline"
            subtitle="Thirty-day actual usage against a rolling seven-day average."
          >
            <EChart option={baselineOption} height={320} />
          </ChartCard>
        </section>

        <ReadingsTable readings={readingsQuery.data ?? []} />
      </div>
    </main>
  );
}
