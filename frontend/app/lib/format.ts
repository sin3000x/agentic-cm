/**
 * Locale-aware formatting shared across routes.
 *
 * The UI is single-locale (zh-CN) and every string is authored inline, so these
 * exist to keep number and date rendering consistent, not as an i18n layer.
 */

const THREAD_TIME = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const DAY = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" });

const DAY_TIME = new Intl.DateTimeFormat("zh-CN", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Placeholder shown while a timestamp has not loaded yet. */
export const TIME_PLACEHOLDER = "时间读取中";

function format(formatter: Intl.DateTimeFormat, value: string | undefined | null): string {
  if (!value) return TIME_PLACEHOLDER;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? TIME_PLACEHOLDER : formatter.format(parsed);
}

/** Timestamp for a Case Thread entry. */
export function formatThreadTime(value: string | undefined | null): string {
  return format(THREAD_TIME, value);
}

/** Date without time, for due dates. */
export function formatDay(value: string | undefined | null): string {
  return format(DAY, value);
}

/** Date and time, for "last updated" style fields. */
export function formatDayTime(value: string | undefined | null): string {
  return format(DAY_TIME, value);
}

/** Grouped number, for quantities shown to users. */
export function formatQuantity(value: number): string {
  return value.toLocaleString("zh-CN");
}
