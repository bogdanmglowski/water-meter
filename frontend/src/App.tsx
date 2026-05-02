import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getAlerts, getConsumption, getCumulative, getDashboard, getReadings } from "./api";
import { AlertPanel } from "./components/AlertPanel";
import { ChartCard } from "./components/ChartCard";
import { EChart, type WaterMeterChartOption } from "./components/EChart";
import { MetricCard } from "./components/MetricCard";
import { ReadingsTable } from "./components/ReadingsTable";
import type { Bucket, RangePreset, UsagePoint } from "./types";
import {
  buildRange,
  formatBucketLabel,
  formatTimestamp,
  formatVolume,
  rollingAverage,
} from "./utils";

type AppPage =
  | "dashboard"
  | "cumulative-trend"
  | "interval-consumption"
  | "daily-baseline"
  | "raw-readings";

const pages = [
  {
    value: "dashboard" as const,
    label: "Dashboard",
    detail: "Current meter state and headline usage totals.",
  },
  {
    value: "cumulative-trend" as const,
    label: "Cumulative Trend",
    detail: "Raw cumulative readings over the selected window.",
  },
  {
    value: "interval-consumption" as const,
    label: "Interval Consumption",
    detail: "Bucketed usage highlights bursts and quiet periods.",
  },
  {
    value: "daily-baseline" as const,
    label: "Daily Baseline",
    detail: "Thirty-day daily totals against a rolling average.",
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
  switch (hash) {
    case "":
    case "#dashboard":
      return "dashboard";
    case "#cumulative-trend":
    case "#time-series":
      return "cumulative-trend";
    case "#interval-consumption":
      return "interval-consumption";
    case "#daily-baseline":
      return "daily-baseline";
    case "#raw-readings":
      return "raw-readings";
    default:
      return "cumulative-trend";
  }
}

function chartAxisLine() {
  return {
    lineStyle: {
      color: "#3a3a3f",
    },
  };
}

function chartAxisLabel() {
  return {
    color: "#6b7280",
  };
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
  const isCumulativePage = page === "cumulative-trend";
  const isConsumptionPage = page === "interval-consumption";
  const isBaselinePage = page === "daily-baseline";
  const isChartPage = isCumulativePage || isConsumptionPage || isBaselinePage;
  const activePageMeta = pages.find((item) => item.value === page) ?? pages[0];
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
    enabled: isCumulativePage,
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
    enabled: isConsumptionPage,
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
    enabled: isBaselinePage,
  });

  const alertsQuery = useQuery({
    queryKey: ["alerts", activeRange.from, activeRange.to, tzOffsetMinutes],
    queryFn: () =>
      getAlerts({
        ...activeRange,
        tzOffsetMinutes,
      }),
    staleTime: 60_000,
    enabled: isCumulativePage,
  });

  const readingsQuery = useQuery({
    queryKey: ["readings", activeRange.from, activeRange.to],
    queryFn: () =>
      getReadings({
        ...activeRange,
        limit: 2_000,
      }),
    staleTime: 60_000,
    enabled: page === "raw-readings",
  });

  const error = isDashboardPage
    ? dashboardQuery.error
    : isCumulativePage
      ? cumulativeQuery.error || alertsQuery.error
      : isConsumptionPage
        ? consumptionQuery.error
        : isBaselinePage
          ? baselineQuery.error
          : readingsQuery.error;

  const dailySeries = baselineQuery.data ?? [];
  const dailyBaseline = rollingAverage(dailySeries, 7);
  const highestConsumptionPoint = (consumptionQuery.data ?? []).reduce<UsagePoint | null>(
    (peak, point) => {
      if (!peak || point.consumptionM3 > peak.consumptionM3) {
        return point;
      }

      return peak;
    },
    null,
  );
  const baselineDaysAboveAverage = dailySeries.reduce((count, point, index) => {
    const average = dailyBaseline[index] ?? point.consumptionM3;
    return point.consumptionM3 > average ? count + 1 : count;
  }, 0);
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
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#14151a",
      borderColor: "#3a3a3f",
      textStyle: { color: "#e5e7eb" },
    },
    grid: { left: 48, right: 20, top: 24, bottom: 40 },
    xAxis: {
      type: "time",
      axisLabel: chartAxisLabel(),
      axisLine: chartAxisLine(),
    },
    yAxis: {
      type: "value",
      name: "m³",
      nameTextStyle: chartAxisLabel(),
      axisLabel: chartAxisLabel(),
      splitLine: { lineStyle: { color: "rgba(58, 58, 63, 0.6)" } },
    },
    series: [
      {
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: "#f472b6" },
        areaStyle: {
          color: "rgba(244, 114, 182, 0.12)",
        },
        data: (cumulativeQuery.data ?? []).map((point) => [
          point.recordedAt,
          point.meterValueM3,
        ]),
      },
    ],
  };

  const consumptionOption: WaterMeterChartOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#14151a",
      borderColor: "#3a3a3f",
      textStyle: { color: "#e5e7eb" },
    },
    grid: { left: 48, right: 20, top: 24, bottom: 56 },
    xAxis: {
      type: "category",
      axisLabel: { ...chartAxisLabel(), rotate: 30 },
      axisLine: chartAxisLine(),
      data: (consumptionQuery.data ?? []).map((point) =>
        formatBucketLabel(point.bucketStart, point.bucketEnd),
      ),
    },
    yAxis: {
      type: "value",
      name: "m³",
      nameTextStyle: chartAxisLabel(),
      axisLabel: chartAxisLabel(),
      splitLine: { lineStyle: { color: "rgba(58, 58, 63, 0.6)" } },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 28,
        itemStyle: {
          color: "#ec4899",
          borderRadius: [8, 8, 2, 2],
        },
        data: (consumptionQuery.data ?? []).map((point) => point.consumptionM3),
      },
    ],
  };

  const baselineOption: WaterMeterChartOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#14151a",
      borderColor: "#3a3a3f",
      textStyle: { color: "#e5e7eb" },
    },
    legend: {
      top: 0,
      textStyle: {
        color: "#e5e7eb",
      },
    },
    grid: { left: 48, right: 20, top: 48, bottom: 56 },
    xAxis: {
      type: "category",
      axisLabel: { ...chartAxisLabel(), rotate: 30 },
      axisLine: chartAxisLine(),
      data: dailySeries.map((point) => formatBucketLabel(point.bucketStart, point.bucketEnd)),
    },
    yAxis: {
      type: "value",
      name: "m³",
      nameTextStyle: chartAxisLabel(),
      axisLabel: chartAxisLabel(),
      splitLine: { lineStyle: { color: "rgba(58, 58, 63, 0.6)" } },
    },
    series: [
      {
        name: "Actual",
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: "#22d3ee" },
        areaStyle: { color: "rgba(34, 211, 238, 0.08)" },
        data: dailySeries.map((point) => point.consumptionM3),
      },
      {
        name: "7-day average",
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, type: "dashed", color: "#c084fc" },
        data: dailyBaseline,
      },
    ],
  };

  const activeRangeSummary = `${formatTimestamp(activeRange.from)} to ${formatTimestamp(activeRange.to)}`;
  const baselineRangeSummary = `${formatTimestamp(baselineRange.from)} to ${formatTimestamp(baselineRange.to)}`;
  const statusRangeLabel = isDashboardPage
    ? "Live summary"
    : isBaselinePage
      ? "Last 30 days"
      : activePresetLabel;
  const statusWindowSummary = isDashboardPage
    ? "Today, last 24h, last 7d, month to date"
    : isBaselinePage
      ? baselineRangeSummary
      : activeRangeSummary;
  const currentSectionTitle = isDashboardPage
    ? "Current meter state"
    : isCumulativePage
      ? "Cumulative meter trend"
      : isConsumptionPage
        ? "Bucketed interval usage"
        : isBaselinePage
          ? "Rolling daily baseline"
          : "Cumulative feed";
  const pageDescription = isDashboardPage
    ? "A cumulative meter feed rendered as a neon control room for live household usage."
    : isCumulativePage
      ? "Track the raw meter register over time to spot resets, stalls, and sudden jumps."
      : isConsumptionPage
        ? "Study grouped consumption bursts across hourly to yearly buckets."
        : isBaselinePage
          ? "Compare the latest 30 days of daily usage against a rolling seven-day average."
          : "Inspect the raw cumulative register stream exactly as PostgreSQL stores it.";
  const statusCommand = isDashboardPage
    ? "GET /api/dashboard"
    : isCumulativePage
      ? "GET /api/series/cumulative"
      : isConsumptionPage
        ? `GET /api/series/consumption?bucket=${bucket}`
        : isBaselinePage
          ? "GET /api/series/consumption?bucket=day"
          : "GET /api/readings?limit=2000";

  return (
    <main className="page-shell">
      <div className="page-noise" />
      <div className="page-glow page-glow--pink" />
      <div className="page-glow page-glow--violet" />
      <div className="page-bg" />
      <div className="page">
        <header className="topbar">
          <div className="topbar__main">
            <div className="brand-block">
              <span className="eyebrow">Synthwave water lab</span>
              <h1>
                Water <span>Meter</span>
              </h1>
              <p>{pageDescription}</p>
            </div>

            <nav className="page-nav" aria-label="Subpages">
              {pages.map((item, index) => (
                <a
                  key={item.value}
                  href={`#${item.value}`}
                  className={item.value === page ? "page-nav__link is-active" : "page-nav__link"}
                  aria-current={item.value === page ? "page" : undefined}
                  onClick={() => setPage(item.value)}
                >
                  <span className="page-nav__index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="page-nav__label">{item.label}</span>
                  <span className="page-nav__detail">{item.detail}</span>
                </a>
              ))}
            </nav>
          </div>

          <div className="status-panel">
            <div className="status-panel__header">
              <span className="status-chip">{activePageMeta.label}</span>
              <span className="status-panel__mono">tz {tzOffsetMinutes >= 0 ? "+" : ""}{tzOffsetMinutes}m</span>
            </div>
            <strong className="status-panel__title">{currentSectionTitle}</strong>
            <p className="status-panel__text">{activePageMeta.detail}</p>
            <div className="command-line">
              <span className="command-line__prompt">$</span>
              <span className="command-line__text">{statusCommand}</span>
            </div>
            <div className="status-panel__meta">
              <div>
                <span className="label">Range</span>
                <strong>{statusRangeLabel}</strong>
              </div>
              <div>
                <span className="label">Window</span>
                <strong>{statusWindowSummary}</strong>
              </div>
            </div>
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
            <section className="hero-grid">
              <div className="hero-card card">
                <div className="hero-card__copy">
                  <span className="eyebrow">Current meter state</span>
                  <div className="hero-card__headline">
                    <span className="hero-card__label">Latest cumulative register</span>
                    <span className="hero-card__tag">read-only feed</span>
                  </div>
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
                  <div className="hero-card__ledger">
                    <div className="hero-card__ledger-row">
                      <span className="label">Source</span>
                      <span className="hero-card__mono">
                        {dashboardQuery.data?.latestReading?.source ?? "n/a"}
                      </span>
                    </div>
                    <div className="hero-card__ledger-row">
                      <span className="label">Alert count</span>
                      <span className="hero-card__mono">
                        {dashboardQuery.data?.summary.activeAlerts ?? 0}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="hero-card__summary">
                  <div>
                    <span className="label">Recent anomalies</span>
                    <strong>{dashboardQuery.data?.summary.anomalyCount ?? 0}</strong>
                  </div>
                  <div>
                    <span className="label">Active alerts</span>
                    <strong>{dashboardQuery.data?.summary.activeAlerts ?? 0}</strong>
                  </div>
                  <div>
                    <span className="label">Month to date</span>
                    <strong>{formatVolume(dashboardQuery.data?.summary.monthToDateM3 ?? 0)}</strong>
                  </div>
                </div>
              </div>

              <aside className="card sidekick-card">
                <div className="sidekick-card__header">
                  <span className="eyebrow">Signal notes</span>
                  <span className="count-pill">v1</span>
                </div>
                <ul className="signal-list">
                  <li>Consumption is derived from cumulative deltas only.</li>
                  <li>Negative jumps are preserved as anomalies instead of hidden.</li>
                  <li>Timezone boundaries follow the browser offset sent to the API.</li>
                </ul>
              </aside>
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
        ) : isChartPage ? (
          <>
            <section className="page-intro-grid">
              <div className="card page-intro">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">
                      {isCumulativePage
                        ? "Cumulative Trend"
                        : isConsumptionPage
                          ? "Interval Consumption"
                          : "Daily Baseline"}
                    </span>
                    <h2>
                      {isCumulativePage
                        ? "Follow the cumulative register"
                        : isConsumptionPage
                          ? "Choose a window and bucket"
                          : "Compare against the rolling baseline"}
                    </h2>
                    <p>
                      {isCumulativePage
                        ? "Inspect the raw cumulative feed across any selected window."
                        : isConsumptionPage
                          ? "Move from short hourly views to broader monthly or yearly summaries."
                          : "This page always compares the latest 30 days of daily totals against a rolling seven-day average."}
                    </p>
                  </div>
                </div>

                {isBaselinePage ? null : (
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
                )}

                {isConsumptionPage ? (
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
                ) : null}

                <p className="range-meta">
                  {isCumulativePage
                    ? `${activePresetLabel} selected. Raw cumulative values span ${activeRangeSummary}.`
                    : isConsumptionPage
                      ? `${activePresetLabel} selected. Interval consumption is grouped as ${activeBucketLabel.toLowerCase()} buckets for ${activeRangeSummary}.`
                      : `Baseline view spans ${baselineRangeSummary} using daily totals only.`}
                </p>
              </div>

              <aside className="card inspector-card">
                <span className="eyebrow">Inspector</span>
                <h2>
                  {isCumulativePage
                    ? "Meter register lens"
                    : isConsumptionPage
                      ? `${activeBucketLabel} lens`
                      : "30-day lens"}
                </h2>
                <p>
                  {isCumulativePage
                    ? "Use the raw curve to identify resets, stalls, and suspicious jumps before looking at alerts."
                    : isConsumptionPage
                      ? "Grouped deltas expose the busiest buckets and make quiet periods obvious."
                      : "Daily totals versus the rolling average show whether higher usage is persistent or temporary."}
                </p>
                <div className="inspector-card__stats">
                  <div>
                    <span className="label">
                      {isCumulativePage
                        ? "Alerts"
                        : isConsumptionPage
                          ? "Buckets"
                          : "Days"}
                    </span>
                    <strong>
                      {isCumulativePage
                        ? alertsQuery.data?.length ?? 0
                        : isConsumptionPage
                          ? consumptionQuery.data?.length ?? 0
                          : dailySeries.length}
                    </strong>
                  </div>
                  <div>
                    <span className="label">
                      {isCumulativePage
                        ? "Samples"
                        : isConsumptionPage
                          ? "Peak"
                          : "Above avg"}
                    </span>
                    <strong>
                      {isCumulativePage
                        ? cumulativeQuery.data?.length ?? 0
                        : isConsumptionPage
                          ? highestConsumptionPoint
                            ? formatVolume(highestConsumptionPoint.consumptionM3)
                            : "No data"
                          : baselineDaysAboveAverage}
                    </strong>
                  </div>
                </div>
              </aside>
            </section>

            <section className="chart-stack">
              {isCumulativePage ? (
                <>
                  <ChartCard
                    title="Cumulative Meter Trend"
                    subtitle="Raw cumulative readings show how the register moves over time."
                  >
                    <EChart option={cumulativeOption} height={380} />
                  </ChartCard>
                  <AlertPanel alerts={alertsQuery.data ?? []} />
                </>
              ) : null}

              {isConsumptionPage ? (
                <ChartCard
                  title="Interval Consumption"
                  subtitle={`Usage grouped by ${activeBucketLabel.toLowerCase()}. Zero-filled buckets expose quiet periods clearly.`}
                >
                  <EChart option={consumptionOption} height={380} />
                </ChartCard>
              ) : null}

              {isBaselinePage ? (
                <ChartCard
                  title="Daily Baseline"
                  subtitle="Thirty-day actual usage against a rolling seven-day average."
                >
                  <EChart option={baselineOption} height={380} />
                </ChartCard>
              ) : null}
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
                Showing up to 2,000 rows for {activeRangeSummary}. Values remain cumulative, not
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
