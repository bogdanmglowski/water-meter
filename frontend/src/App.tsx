import { useEffect, useState } from "react";
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

type AppPage = "dashboard" | "time-series" | "raw-readings";

const pages = [
  {
    value: "dashboard" as const,
    label: "Dashboard",
    detail: "Current meter state and headline usage totals.",
  },
  {
    value: "time-series" as const,
    label: "Time Series",
    detail: "Charts, summaries, and alert trends.",
  },
  {
    value: "raw-readings" as const,
    label: "Raw Readings",
    detail: "Direct cumulative values from PostgreSQL.",
  },
];

const presets = [
  { value: "24h" as const, label: "Last 24 hours" },
  { value: "3d" as const, label: "Last 3 days" },
  { value: "7d" as const, label: "Last 7 days" },
  { value: "30d" as const, label: "Last 30 days" },
  { value: "90d" as const, label: "Last 90 days" },
  { value: "365d" as const, label: "Last 12 months" },
];

const buckets = [
  { value: "hour" as const, label: "Hourly" },
  { value: "day" as const, label: "Daily" },
  { value: "week" as const, label: "Weekly" },
  { value: "month" as const, label: "Monthly" },
  { value: "year" as const, label: "Yearly" },
];

function pageFromHash(hash: string): AppPage {
  if (hash === "#dashboard" || hash === "") {
    return "dashboard";
  }

  return hash === "#raw-readings" ? "raw-readings" : "time-series";
}

export default function App() {
  const readingsPerPage = 30;
  const [page, setPage] = useState<AppPage>(() => pageFromHash(window.location.hash));
  const [preset, setPreset] = useState<RangePreset>("30d");
  const [bucket, setBucket] = useState<Bucket>("day");
  const [rangeEnd, setRangeEnd] = useState(() => new Date());
  const [readingsPage, setReadingsPage] = useState(1);

  useEffect(() => {
    const syncPage = () => {
      setPage(pageFromHash(window.location.hash));
    };

    window.addEventListener("hashchange", syncPage);
    return () => {
      window.removeEventListener("hashchange", syncPage);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRangeEnd(new Date());
    }, 60_000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    setReadingsPage(1);
  }, [page, preset]);

  const tzOffsetMinutes = -new Date().getTimezoneOffset();
  const isDashboardPage = page === "dashboard";
  const isTimeSeriesPage = page === "time-series";
  const activeRange = buildRange(preset, rangeEnd);
  const baselineRange = buildRange("30d", rangeEnd);
  const activePresetLabel =
    presets.find((option) => option.value === preset)?.label ?? "Selected range";
  const activeBucketLabel =
    buckets.find((option) => option.value === bucket)?.label ?? "Selected bucket";

  const dashboardQuery = useQuery({
    queryKey: ["dashboard", tzOffsetMinutes],
    queryFn: () => getDashboard(tzOffsetMinutes),
    staleTime: 60_000,
    refetchInterval: isDashboardPage ? 60_000 : false,
    enabled: isDashboardPage,
  });

  const cumulativeQuery = useQuery({
    queryKey: ["cumulative", activeRange.from, activeRange.to],
    queryFn: () => getCumulative(activeRange),
    staleTime: 60_000,
    enabled: isTimeSeriesPage,
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
    enabled: isTimeSeriesPage,
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
    enabled: isTimeSeriesPage,
  });

  const alertsQuery = useQuery({
    queryKey: ["alerts", activeRange.from, activeRange.to, tzOffsetMinutes],
    queryFn: () =>
      getAlerts({
        ...activeRange,
        tzOffsetMinutes,
      }),
    staleTime: 60_000,
    enabled: isTimeSeriesPage,
  });

  const readingsQuery = useQuery({
    queryKey: ["readings", activeRange.from, activeRange.to],
    queryFn: () =>
      getReadings({
        ...activeRange,
        limit: 2_000,
      }),
    staleTime: 60_000,
    enabled: !isTimeSeriesPage,
  });

  const error = isTimeSeriesPage
    ? cumulativeQuery.error ||
      consumptionQuery.error ||
      baselineQuery.error ||
      alertsQuery.error
    : isDashboardPage
      ? dashboardQuery.error
    : readingsQuery.error;

  const dailySeries = baselineQuery.data ?? [];
  const dailyBaseline = rollingAverage(dailySeries, 7);
  const rawReadings = readingsQuery.data ?? [];
  const totalReadingPages = Math.max(1, Math.ceil(rawReadings.length / readingsPerPage));
  const activeReadingsPage = Math.min(readingsPage, totalReadingPages);
  const pagedReadings = rawReadings.slice(
    (activeReadingsPage - 1) * readingsPerPage,
    activeReadingsPage * readingsPerPage,
  );

  useEffect(() => {
    setReadingsPage((current) => Math.min(current, totalReadingPages));
  }, [totalReadingPages]);

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

  const rangeSummary = `${formatTimestamp(activeRange.from)} to ${formatTimestamp(activeRange.to)}`;
  return (
    <main className="page-shell">
      <div className="page-bg" />
      <div className="page">
        <header className="topbar">
          <div className="topbar__main">
            <div>
              <span className="eyebrow">Self-hosted analytics</span>
              <h1>Water Meter</h1>
              <p>
                {isDashboardPage
                  ? "Start with the current meter state and the headline water-usage totals."
                  : isTimeSeriesPage
                  ? "Browse time-series windows, compare bucketed usage, and review alert signals."
                  : "Inspect the raw cumulative meter feed without chart aggregation in the way."}
              </p>
            </div>

            <nav className="page-nav" aria-label="Subpages">
              {pages.map((item) => (
                <a
                  key={item.value}
                  href={`#${item.value}`}
                  className={item.value === page ? "page-nav__link is-active" : "page-nav__link"}
                  aria-current={item.value === page ? "page" : undefined}
                  onClick={() => setPage(item.value)}
                >
                  <span className="page-nav__label">{item.label}</span>
                  <span className="page-nav__detail">{item.detail}</span>
                </a>
              ))}
            </nav>
          </div>

          <div className="status-panel">
            <span className="status-chip">
              {isDashboardPage ? "Dashboard" : isTimeSeriesPage ? "Time Series" : "Raw Feed"}
            </span>
          </div>
        </header>

        {error ? (
          <section className="card error-card">
            <strong>API request failed.</strong>
            <p>{error.message}</p>
          </section>
        ) : null}

        {isDashboardPage ? (
          <>
            <section className="hero-grid hero-grid--single">
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
                  <strong>{dashboardQuery.data?.summary.anomalyCount ?? 0}</strong>
                  <span className="label">Active alerts</span>
                  <strong>{dashboardQuery.data?.summary.activeAlerts ?? 0}</strong>
                </div>
              </div>
            </section>

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
          </>
        ) : isTimeSeriesPage ? (
          <>
            <section className="card page-intro">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Time Series</span>
                  <h2>Choose a window and bucket</h2>
                  <p>
                    Move from short hourly views to broader monthly or yearly summaries without
                    leaving the charts page.
                  </p>
                </div>
              </div>

              <div className="control-group">
                <span className="label">Range</span>
                <div className="segmented">
                  {presets.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={item.value === preset ? "is-active" : ""}
                      onClick={() => {
                        setRangeEnd(new Date());
                        setPreset(item.value);
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="control-group">
                <span className="label">Buckets</span>
                <div className="segmented segmented--compact">
                  {buckets.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={item.value === bucket ? "is-active" : ""}
                      onClick={() => setBucket(item.value)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <p className="range-meta">
                {activePresetLabel} selected. Interval consumption is grouped as{" "}
                {activeBucketLabel.toLowerCase()} buckets for {rangeSummary}.
              </p>
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
                subtitle={`Usage grouped by ${activeBucketLabel.toLowerCase()}. Zero-filled buckets expose quiet periods clearly.`}
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
          </>
        ) : (
          <>
            <section className="card page-intro">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Raw Feed</span>
                  <h2>Inspect cumulative readings directly</h2>
                  <p>
                    Review the exact values stored in PostgreSQL across the same time windows used
                    by the chart page.
                  </p>
                </div>
                <span className="count-pill">{rawReadings.length}</span>
              </div>

              <div className="control-group">
                <span className="label">Range</span>
                <div className="segmented">
                  {presets.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={item.value === preset ? "is-active" : ""}
                      onClick={() => {
                        setRangeEnd(new Date());
                        setPreset(item.value);
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <p className="range-meta">
                Showing up to 2,000 rows for {rangeSummary}. Values remain cumulative, not
                per-bucket deltas.
              </p>
            </section>

            <ReadingsTable
              readings={pagedReadings}
              currentPage={activeReadingsPage}
              totalPages={totalReadingPages}
              totalReadings={rawReadings.length}
              pageSize={readingsPerPage}
              onPreviousPage={() => setReadingsPage((current) => Math.max(1, current - 1))}
              onNextPage={() =>
                setReadingsPage((current) => Math.min(totalReadingPages, current + 1))
              }
            />
          </>
        )}
      </div>
    </main>
  );
}
