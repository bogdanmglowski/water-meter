import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteReading,
  getAlerts,
  getAnomalies,
  getConsumption,
  getCumulative,
  getDashboard,
  getReadings,
  getReaderGalleryPage,
} from "./api";
import { AnomaliesTable } from "./components/AnomaliesTable";
import { AlertPanel } from "./components/AlertPanel";
import { ChartCard } from "./components/ChartCard";
import { EChart, type WaterMeterChartOption } from "./components/EChart";
import { MetricCard } from "./components/MetricCard";
import { ReadingsTable } from "./components/ReadingsTable";
import type { Bucket, RangePreset, ReaderGallerySection, ReaderImageDayGroup, ReaderImageItem, Reading } from "./types";
import {
  buildRange,
  formatBucketLabel,
  formatDateTimeInput,
  formatTimestamp,
  formatVolume,
  formatVolumeAxis,
  rollingAverage,
  toIsoTimestamp,
} from "./utils";

interface AppliedRange {
  from: string;
  to: string;
}

interface RangeInputs {
  from: string;
  to: string;
}

type AppPage =
  | "dashboard"
  | "cumulative-trend"
  | "interval-consumption"
  | "daily-baseline"
  | "raw-readings"
  | "anomalies"
  | "reader-gallery";

const pages = [
  {
    value: "dashboard" as const,
    label: "Dashboard",
  },
  {
    value: "cumulative-trend" as const,
    label: "Cumulative Trend",
  },
  {
    value: "interval-consumption" as const,
    label: "Interval Consumption",
  },
  {
    value: "daily-baseline" as const,
    label: "Daily Baseline",
  },
  {
    value: "raw-readings" as const,
    label: "Raw Readings",
  },
  {
    value: "anomalies" as const,
    label: "Anomalies",
  },
  {
    value: "reader-gallery" as const,
    label: "Reader Gallery",
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
    case "#anomalies":
      return "anomalies";
    case "#reader-gallery":
      return "reader-gallery";
    default:
      return "cumulative-trend";
  }
}

function renderReaderImageCard(image: ReaderImageItem) {
  return (
    <article key={image.url} className="image-card">
      <a href={image.url} target="_blank" rel="noreferrer" className="image-card__media-link">
        <img src={image.url} alt={image.name} className="image-card__image" loading="lazy" />
      </a>
      <div className="image-card__meta">
        <strong>{image.name}</strong>
        <span>{formatTimestamp(image.capturedAt)}</span>
      </div>
    </article>
  );
}

function renderReaderDayGroup(dayGroup: ReaderImageDayGroup, defaultOpen = false) {
  return (
    <details key={dayGroup.day} className="image-day-group" open={defaultOpen}>
      <summary className="image-day-group__summary">
        <div>
          <strong>{formatTimestamp(`${dayGroup.day}T00:00:00Z`)}</strong>
          <span>{dayGroup.items.length} image{dayGroup.items.length === 1 ? "" : "s"}</span>
        </div>
        <span className="count-pill">{dayGroup.items.length}</span>
      </summary>
      <div className="image-grid image-grid--grouped">
        {dayGroup.items.map((image) => renderReaderImageCard(image))}
      </div>
    </details>
  );
}

function renderReaderSectionPagination(
  section: ReaderGallerySection | undefined,
  label: string,
  onPreviousPage: () => void,
  onNextPage: () => void,
) {
  if (!section || section.totalPages <= 1) {
    return null;
  }

  return (
    <div className="image-gallery__pagination">
      <button type="button" onClick={onPreviousPage} disabled={section.page <= 1}>
        Previous {label} days
      </button>
      <span>
        Page {section.page} of {section.totalPages}
      </span>
      <button type="button" onClick={onNextPage} disabled={section.page >= section.totalPages}>
        Next {label} days
      </button>
    </div>
  );
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

function chartValueTooltip(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "n/a";
  }

  return formatVolume(value);
}

function rangeToInputs(range: AppliedRange): RangeInputs {
  return {
    from: formatDateTimeInput(range.from),
    to: formatDateTimeInput(range.to),
  };
}

export default function App() {
  const readingsPerPage = 30;
  const queryClient = useQueryClient();
  const [page, setPage] = useState<AppPage>(() => pageFromHash(window.location.hash));
  const [preset, setPreset] = useState<RangePreset>("30d");
  const [bucket, setBucket] = useState<Bucket>("day");
  const [rangeEnd, setRangeEnd] = useState(() => new Date());
  const [customRange, setCustomRange] = useState<AppliedRange | null>(null);
  const [rangeInputs, setRangeInputs] = useState<RangeInputs>(() =>
    rangeToInputs(buildRange("30d")),
  );
  const [isEditingRange, setIsEditingRange] = useState(false);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const [readingsPage, setReadingsPage] = useState(1);
  const [originalGalleryPage, setOriginalGalleryPage] = useState(1);
  const [processedGalleryPage, setProcessedGalleryPage] = useState(1);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const activeRange = customRange ?? buildRange(preset, rangeEnd);

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
    if (customRange || isEditingRange) {
      return;
    }

    setRangeInputs(rangeToInputs(activeRange));
  }, [customRange, isEditingRange, activeRange.from, activeRange.to]);

  useEffect(() => {
    setReadingsPage(1);
  }, [page, preset]);

  function handlePresetChange(nextPreset: RangePreset) {
    const nextEnd = new Date();
    const nextRange = buildRange(nextPreset, nextEnd);

    setPreset(nextPreset);
    setCustomRange(null);
    setRangeEnd(nextEnd);
    setRangeInputs(rangeToInputs(nextRange));
    setIsEditingRange(false);
    setRangeError(null);
    setReadingsPage(1);
  }

  function handleRangeInputChange(field: keyof RangeInputs, value: string) {
    setIsEditingRange(true);
    setRangeInputs((current) => ({
      ...current,
      [field]: value,
    }));
    setRangeError(null);
  }

  function handleApplyRange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const from = toIsoTimestamp(rangeInputs.from);
    const to = toIsoTimestamp(rangeInputs.to);

    if (!from || !to) {
      setRangeError("Enter both start and end date/time values.");
      return;
    }

    const fromDate = new Date(rangeInputs.from);
    const toDate = new Date(rangeInputs.to);
    const now = new Date();
    now.setSeconds(0, 0);
    const fromMillis = fromDate.getTime();
    const toMillis = toDate.getTime();

    if (fromMillis >= toMillis) {
      setRangeError("Start date/time must be earlier than end date/time.");
      return;
    }

    if (fromDate > now || toDate > now) {
      setRangeError("Date/time range cannot extend into the future.");
      return;
    }

    const maxTo = new Date(fromDate);
    maxTo.setFullYear(maxTo.getFullYear() + 1);

    if (toDate > maxTo) {
      setRangeError("Custom range cannot exceed one year.");
      return;
    }

    setCustomRange({ from, to });
    setIsEditingRange(false);
    setRangeError(null);
    setReadingsPage(1);
  }

  const tzOffsetMinutes = -new Date().getTimezoneOffset();
  const isDashboardPage = page === "dashboard";
  const isCumulativePage = page === "cumulative-trend";
  const isConsumptionPage = page === "interval-consumption";
  const isBaselinePage = page === "daily-baseline";
  const isAnomaliesPage = page === "anomalies";
  const isReaderGalleryPage = page === "reader-gallery";
  const isChartPage = isCumulativePage || isConsumptionPage || isBaselinePage;

  useEffect(() => {
    if (!isReaderGalleryPage) {
      return;
    }

    setOriginalGalleryPage(1);
    setProcessedGalleryPage(1);
  }, [isReaderGalleryPage]);
  const activePresetLabel =
    presets.find((option) => option.value === preset)?.label ?? "Selected range";
  const activeBucketLabel =
    buckets.find((option) => option.value === bucket)?.label ?? "Selected bucket";
  const activeRangeLabel = customRange ? "Custom range" : activePresetLabel;
  const latestSelectableDateTime = formatDateTimeInput(new Date());
  const maxFromInput =
    rangeInputs.to && rangeInputs.to < latestSelectableDateTime
      ? rangeInputs.to
      : latestSelectableDateTime;

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
    queryKey: ["baseline", activeRange.from, activeRange.to, tzOffsetMinutes],
    queryFn: () =>
      getConsumption({
        ...activeRange,
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

  const anomaliesQuery = useQuery({
    queryKey: ["anomalies", activeRange.from, activeRange.to],
    queryFn: () => getAnomalies(activeRange),
    staleTime: 60_000,
    enabled: isAnomaliesPage,
  });

  const readingsQuery = useQuery({
    queryKey: ["readings", activeRange.from, activeRange.to, readingsPage, readingsPerPage],
    queryFn: () =>
      getReadings({
        ...activeRange,
        page: readingsPage,
        pageSize: readingsPerPage,
      }),
    staleTime: 60_000,
    enabled: page === "raw-readings",
  });

  const readerGalleryQuery = useQuery({
    queryKey: ["reader-gallery", originalGalleryPage, processedGalleryPage],
    queryFn: () =>
      getReaderGalleryPage({
        originalPage: originalGalleryPage,
        processedPage: processedGalleryPage,
        pageSize: 7,
      }),
    staleTime: 30_000,
    refetchInterval: isReaderGalleryPage ? 30_000 : false,
    enabled: isReaderGalleryPage,
  });

  const deleteReadingMutation = useMutation({
    mutationFn: (id: number) => deleteReading(id),
    onSuccess: async () => {
      setDeleteError(null);
      const currentPageTotal = readingsQuery.data?.items.length ?? 0;
      const nextTotal = Math.max(0, (readingsQuery.data?.totalCount ?? 0) - 1);
      const shouldGoBackPage = readingsPage > 1 && currentPageTotal <= 1 && nextTotal > 0;

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["readings"] }),
        queryClient.invalidateQueries({ queryKey: ["anomalies"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["cumulative"] }),
        queryClient.invalidateQueries({ queryKey: ["consumption"] }),
        queryClient.invalidateQueries({ queryKey: ["baseline"] }),
        queryClient.invalidateQueries({ queryKey: ["alerts"] }),
      ]);

      if (shouldGoBackPage) {
        setReadingsPage((current) => current - 1);
        return;
      }
    },
    onError: (error) => {
      setDeleteError(error instanceof Error ? error.message : "Delete request failed.");
    },
  });

  const error = isDashboardPage
    ? dashboardQuery.error
    : isCumulativePage
      ? cumulativeQuery.error || alertsQuery.error
      : isConsumptionPage
          ? consumptionQuery.error
          : isBaselinePage
            ? baselineQuery.error
              : page === "raw-readings"
                ? readingsQuery.error
                : isReaderGalleryPage
                  ? readerGalleryQuery.error
                  : anomaliesQuery.error;

  const dailySeries = baselineQuery.data ?? [];
  const dailyBaseline = rollingAverage(dailySeries, 7);
  const rawReadingsPage = readingsQuery.data;
  const rawReadings = rawReadingsPage?.items ?? [];
  const totalReadingPages = rawReadingsPage?.totalPages ?? 1;
  const activeReadingsPage = rawReadingsPage?.page ?? readingsPage;
  const totalReadings = rawReadingsPage?.totalCount ?? 0;
  const readerGallery = readerGalleryQuery.data;
  const cumulativeValues = (cumulativeQuery.data ?? []).map((point) => point.meterValueM3);
  const cumulativeMin = cumulativeValues.length > 0 ? Math.min(...cumulativeValues) : undefined;
  const cumulativeMax = cumulativeValues.length > 0 ? Math.max(...cumulativeValues) : undefined;
  const cumulativePadding =
    cumulativeMin !== undefined && cumulativeMax !== undefined
      ? Math.max(1, Math.ceil((cumulativeMax - cumulativeMin || 10) * 0.08))
      : undefined;

  function handleDeleteReading(reading: Reading) {
    const shouldDelete = window.confirm(
      `Delete reading from ${formatTimestamp(reading.recordedAt)}? This will remove it from the database.`,
    );

    if (!shouldDelete) {
      return;
    }

    deleteReadingMutation.mutate(reading.id);
  }

  const cumulativeOption: WaterMeterChartOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#14151a",
      borderColor: "#3a3a3f",
      textStyle: { color: "#e5e7eb" },
      valueFormatter: chartValueTooltip,
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
      min:
        cumulativeMin !== undefined && cumulativePadding !== undefined
          ? cumulativeMin - cumulativePadding
          : undefined,
      max:
        cumulativeMax !== undefined && cumulativePadding !== undefined
          ? cumulativeMax + cumulativePadding
          : undefined,
      nameTextStyle: chartAxisLabel(),
      axisLabel: {
        ...chartAxisLabel(),
        formatter: (value: number) => formatVolumeAxis(value),
      },
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
      valueFormatter: chartValueTooltip,
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
      axisLabel: {
        ...chartAxisLabel(),
        formatter: (value: number) => formatVolumeAxis(value),
      },
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
      valueFormatter: chartValueTooltip,
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
      axisLabel: {
        ...chartAxisLabel(),
        formatter: (value: number) => formatVolumeAxis(value),
      },
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
  const rangeControls = (
    <>
      <div className="control-group">
        <span className="label">Presets</span>
        <div className="segmented">
          {presets.map((item) => (
            <button
              key={item.value}
              type="button"
              className={!customRange && item.value === preset ? "is-active" : ""}
              onClick={() => handlePresetChange(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <form className="control-group range-filter" onSubmit={handleApplyRange}>
        <span className="label">Date and time</span>
        <div className="range-input-grid">
          <label className="range-field">
            <span className="range-field__label">From</span>
            <input
              type="datetime-local"
              step="60"
              value={rangeInputs.from}
              max={maxFromInput || undefined}
              onChange={(event) => handleRangeInputChange("from", event.target.value)}
            />
          </label>

          <label className="range-field">
            <span className="range-field__label">To</span>
            <input
              type="datetime-local"
              step="60"
              value={rangeInputs.to}
              min={rangeInputs.from || undefined}
              max={latestSelectableDateTime || undefined}
              onChange={(event) => handleRangeInputChange("to", event.target.value)}
            />
          </label>
        </div>

        <div className="range-actions">
          <button type="submit" className="range-apply-button">
            Apply range
          </button>
          <p className="range-hint">{activeRangeLabel} active. Times use your browser timezone.</p>
        </div>

        {rangeError ? <p className="range-error">{rangeError}</p> : null}
      </form>
    </>
  );

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
              <h1>
                Water <span>Meter</span>
              </h1>
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
                </a>
              ))}
            </nav>
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
                          : "Compare any window against the rolling baseline"}
                    </h2>
                    <p>
                      {isCumulativePage
                        ? "Inspect the raw cumulative feed across any selected window, including liter precision in the last three digits."
                        : isConsumptionPage
                          ? "Move from short hourly views to broader monthly or yearly summaries."
                          : "This page groups the selected window into daily totals and overlays a rolling seven-day average."}
                    </p>
                  </div>
                </div>

                {rangeControls}

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
                    ? `${activeRangeLabel} selected. Raw cumulative values span ${activeRangeSummary}, with the last three digits representing liters.`
                    : isConsumptionPage
                      ? `${activeRangeLabel} selected. Interval consumption is grouped as ${activeBucketLabel.toLowerCase()} buckets for ${activeRangeSummary}.`
                      : `${activeRangeLabel} selected. Daily totals span ${activeRangeSummary}, with a rolling seven-day average overlay.`}
                </p>
              </div>
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
                  subtitle="Selected-window daily usage against a rolling seven-day average."
                >
                  <EChart option={baselineOption} height={380} />
                </ChartCard>
              ) : null}
            </section>
          </>
        ) : isAnomaliesPage ? (
          <>
            <section className="card page-intro">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Skipped OCR Jumps</span>
                    <h2>Inspect anomaly readings directly</h2>
                    <p>
                      These readings were not inserted into the main meter feed because they exceeded
                     the configured positive jump threshold after the full liter-precision register was interpreted.
                    </p>
                </div>
                <span className="count-pill">{anomaliesQuery.data?.length ?? 0}</span>
              </div>

              {rangeControls}

              <p className="range-meta">
                Showing skipped anomaly rows for {activeRangeSummary}. Each row includes the
                immediately previous reading and the jump amount that triggered the skip.
              </p>
            </section>

            <AnomaliesTable anomalies={anomaliesQuery.data ?? []} />
          </>
        ) : isReaderGalleryPage ? (
          <>
            <section className="card page-intro">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Reader Images</span>
                  <h2>Inspect live crop and archived captures</h2>
                  <p>
                    View the latest crop used by OCR, plus the original saved frames and their
                    processed crop counterparts.
                  </p>
                </div>
                <span className="count-pill">
                  {(readerGallery?.originalImages.totalDays ?? 0) +
                    (readerGallery?.processedImages.totalDays ?? 0)}
                </span>
              </div>

              <p className="range-meta">
                The current crop refreshes from the reader runtime directory. Archived images are
                grouped by day, newest first.
              </p>
            </section>

            <section className="grid-two">
              <section className="card image-feature-card">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">Current Crop</span>
                    <h2>Latest OCR input</h2>
                    <p>The file currently written to `meter-crop.png`.</p>
                  </div>
                </div>

                {readerGallery?.currentCropUrl ? (
                  <a
                    href={readerGallery.currentCropUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="image-feature"
                  >
                    <img
                      src={readerGallery.currentCropUrl}
                      alt="Current OCR crop"
                      className="image-feature__image"
                    />
                  </a>
                ) : (
                  <div className="empty-state">
                    <strong>No current crop available.</strong>
                    <p>Run the reader once to generate `meter-crop.png`.</p>
                  </div>
                )}
              </section>

              <section className="card image-gallery-card">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">Original Captures</span>
                    <h2>Saved reader photos</h2>
                    <p>Full frames archived by the reader before OCR, grouped by capture day.</p>
                  </div>
                  <span className="count-pill">{readerGallery?.originalImages.totalDays ?? 0}</span>
                </div>

                {renderReaderSectionPagination(
                  readerGallery?.originalImages,
                  "original",
                  () => setOriginalGalleryPage((current) => Math.max(1, current - 1)),
                  () =>
                    setOriginalGalleryPage((current) =>
                      Math.min(readerGallery?.originalImages.totalPages ?? current, current + 1),
                    ),
                )}

                {readerGallery && readerGallery.originalImages.dayGroups.length > 0 ? (
                  <div className="image-day-group-list">
                    {readerGallery.originalImages.dayGroups.map((dayGroup, index) =>
                      renderReaderDayGroup(dayGroup, index === 0),
                    )}
                  </div>
                ) : (
                  <div className="empty-state">
                    <strong>No original captures yet.</strong>
                    <p>Persisted reader frames will appear here.</p>
                  </div>
                )}
              </section>
            </section>

            <section className="card image-gallery-card">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Processed Crops</span>
                  <h2>Archived OCR crops</h2>
                  <p>Processed crop snapshots stored alongside persisted original captures.</p>
                </div>
                <span className="count-pill">{readerGallery?.processedImages.totalDays ?? 0}</span>
              </div>

              {renderReaderSectionPagination(
                readerGallery?.processedImages,
                "processed",
                () => setProcessedGalleryPage((current) => Math.max(1, current - 1)),
                () =>
                  setProcessedGalleryPage((current) =>
                    Math.min(readerGallery?.processedImages.totalPages ?? current, current + 1),
                  ),
              )}

              {readerGallery && readerGallery.processedImages.dayGroups.length > 0 ? (
                <div className="image-day-group-list">
                  {readerGallery.processedImages.dayGroups.map((dayGroup, index) =>
                    renderReaderDayGroup(dayGroup, index === 0),
                  )}
                </div>
              ) : (
                <div className="empty-state">
                  <strong>No processed crops yet.</strong>
                  <p>Processed crops are archived when the reader persists an original capture.</p>
                </div>
              )}
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
                    Review the exact values stored in PostgreSQL for the same date/time windows used
                    by the chart pages. The last three digits represent liters.
                  </p>
                </div>
                <span className="count-pill">{totalReadings}</span>
              </div>

              {rangeControls}

              <p className="range-meta">
                Server pagination is active for {activeRangeSummary}. The delta column shows usage
                between each row and the immediately previous reading.
              </p>
            </section>

            {deleteError ? (
              <section className="card error-card">
                <strong>Delete request failed.</strong>
                <p>{deleteError}</p>
              </section>
            ) : null}

            <ReadingsTable
              readings={rawReadings}
              currentPage={activeReadingsPage}
              totalPages={totalReadingPages}
              totalReadings={totalReadings}
              pageSize={readingsPerPage}
              isDeletingId={deleteReadingMutation.isPending ? deleteReadingMutation.variables ?? null : null}
              isDeletePending={deleteReadingMutation.isPending}
              onPreviousPage={() => setReadingsPage((current) => Math.max(1, current - 1))}
              onNextPage={() =>
                setReadingsPage((current) => Math.min(totalReadingPages, current + 1))
              }
              onDeleteReading={handleDeleteReading}
            />
          </>
        )}
      </div>
    </main>
  );
}
