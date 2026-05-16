import type { RangePreset, UsagePoint } from "./types";

type LegacyOffsetDateTimeTuple = readonly [
  year: number,
  ordinal: number,
  hour: number,
  minute: number,
  second: number,
  nanosecond: number,
  offsetHours: number,
  offsetMinutes: number,
  offsetSeconds: number,
];

const dtf = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const preciseDateTime = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const shortDate = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
});

const weekdayDate = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
});

const monthYear = new Intl.DateTimeFormat(undefined, {
  month: "short",
  year: "numeric",
});

const yearOnly = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
});

export function buildRange(preset: RangePreset, end = new Date()) {
  const now = new Date(end);
  now.setSeconds(0, 0);
  const start = new Date(now);

  switch (preset) {
    case "24h":
      start.setHours(start.getHours() - 24);
      break;
    case "3d":
      start.setDate(start.getDate() - 3);
      break;
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "30d":
      start.setDate(start.getDate() - 30);
      break;
    case "90d":
      start.setDate(start.getDate() - 90);
      break;
    case "365d":
      start.setDate(start.getDate() - 365);
      break;
  }

  return {
    from: start.toISOString(),
    to: now.toISOString(),
  };
}

export function formatVolume(value: number) {
  const liters = Math.round(value);
  const sign = liters < 0 ? "-" : "";
  const absoluteLiters = Math.abs(liters);
  const cubicMeters = Math.floor(absoluteLiters / 1_000);
  const remainderLiters = String(absoluteLiters % 1_000).padStart(3, "0");
  return `${sign}${cubicMeters}.${remainderLiters} m³`;
}

export function formatVolumeAxis(value: number) {
  const liters = Math.round(value);
  const sign = liters < 0 ? "-" : "";
  const absoluteLiters = Math.abs(liters);
  const cubicMeters = Math.floor(absoluteLiters / 1_000);
  const remainderLiters = String(absoluteLiters % 1_000).padStart(3, "0");

  return `${sign}${cubicMeters}.${remainderLiters}`;
}

function isValidDate(value: Date) {
  return !Number.isNaN(value.getTime());
}

function isoFallback(value: Date) {
  try {
    return value.toISOString();
  } catch {
    return null;
  }
}

function safeFormatDate(formatter: Intl.DateTimeFormat, value: Date) {
  if (!isValidDate(value)) {
    return null;
  }

  try {
    return formatter.format(value);
  } catch {
    return isoFallback(value);
  }
}

function parseLegacyOffsetDateTime(value: readonly unknown[]) {
  if (value.length !== 9 || !value.every((item) => typeof item === "number")) {
    return null;
  }

  const [
    year,
    ordinal,
    hour,
    minute,
    second,
    nanosecond,
    offsetHours,
    offsetMinutes,
    offsetSeconds,
  ] = value as LegacyOffsetDateTimeTuple;

  const milliseconds = Math.trunc(nanosecond / 1_000_000);
  const utcMillis = Date.UTC(year, 0, ordinal, hour, minute, second, milliseconds);
  const offsetMillis = (offsetHours * 3_600 + offsetMinutes * 60 + offsetSeconds) * 1_000;
  const parsed = new Date(utcMillis - offsetMillis);

  return isValidDate(parsed) ? parsed : null;
}

function parseStringTimestamp(value: string) {
  const parsed = new Date(value);
  if (isValidDate(parsed)) {
    return parsed;
  }

  const normalized = value.replace(
    /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}(?:\.\d+)?) ([+-]\d{2}:\d{2})(?::\d{2})$/,
    "$1T$2$3",
  );

  if (normalized !== value) {
    const fallback = new Date(normalized);
    if (isValidDate(fallback)) {
      return fallback;
    }
  }

  return null;
}

export function parseTimestamp(value: unknown) {
  if (value instanceof Date) {
    return isValidDate(value) ? value : null;
  }

  if (typeof value === "string") {
    return parseStringTimestamp(value);
  }

  if (typeof value === "number") {
    const parsed = new Date(value);
    return isValidDate(parsed) ? parsed : null;
  }

  if (Array.isArray(value)) {
    return parseLegacyOffsetDateTime(value);
  }

  return null;
}

export function toIsoTimestamp(value: unknown) {
  return parseTimestamp(value)?.toISOString() ?? null;
}

export function formatTimestamp(value: unknown) {
  const parsed = parseTimestamp(value);
  return parsed ? safeFormatDate(dtf, parsed) ?? "Unknown time" : "Unknown time";
}

export function formatPreciseTimestamp(value: unknown) {
  const parsed = parseTimestamp(value);
  return parsed ? safeFormatDate(preciseDateTime, parsed) ?? "Unknown time" : "Unknown time";
}

export function formatDateTimeInput(value: unknown) {
  const parsed = parseTimestamp(value);
  if (!parsed) {
    return "";
  }

  const year = String(parsed.getFullYear());
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hour = String(parsed.getHours()).padStart(2, "0");
  const minute = String(parsed.getMinutes()).padStart(2, "0");

  return `${year}-${month}-${day}T${hour}:${minute}`;
}

export function formatBucketLabel(bucketStart: unknown, bucketEnd: unknown) {
  const start = parseTimestamp(bucketStart);
  const end = parseTimestamp(bucketEnd);
  if (!start || !end) {
    return "Unknown period";
  }

  const diffHours = Math.round((end.getTime() - start.getTime()) / 3_600_000);
  const diffDays = diffHours / 24;

  if (diffHours <= 1) {
    return safeFormatDate(dtf, start) ?? "Unknown period";
  }

  if (diffDays <= 2) {
    return safeFormatDate(shortDate, start) ?? "Unknown period";
  }

  if (diffDays <= 14) {
    return safeFormatDate(weekdayDate, start) ?? "Unknown period";
  }

  if (diffDays <= 45) {
    return safeFormatDate(monthYear, start) ?? "Unknown period";
  }

  if (diffDays <= 370) {
    return safeFormatDate(monthYear, start) ?? "Unknown period";
  }

  return safeFormatDate(yearOnly, start) ?? "Unknown period";
}

export function rollingAverage(points: UsagePoint[], windowSize: number) {
  return points.map((point, index) => {
    const slice = points.slice(Math.max(0, index - windowSize + 1), index + 1);
    const total = slice.reduce((sum, item) => sum + item.consumptionM3, 0);
    return Math.round(total / slice.length);
  });
}
