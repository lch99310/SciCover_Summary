import { format } from 'date-fns';

/**
 * Safely format a date string.  Returns a formatted string or a fallback
 * value if the input is empty, null, or otherwise unparseable.
 */
export function safeFormatDate(
  dateStr: string | undefined | null,
  fmt: string = 'MMM d, yyyy',
  fallback: string = '—',
): string {
  if (!dateStr || !dateStr.trim()) return fallback;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return fallback;
    return format(d, fmt);
  } catch {
    return fallback;
  }
}

/**
 * Safely parse a date string and return its year, or NaN if invalid.
 */
export function safeGetYear(dateStr: string | undefined | null): number {
  if (!dateStr || !dateStr.trim()) return NaN;
  const d = new Date(dateStr);
  return isNaN(d.getTime()) ? NaN : d.getFullYear();
}

/**
 * Safely parse a date string and return its month (0–11), or NaN if invalid.
 */
export function safeGetMonth(dateStr: string | undefined | null): number {
  if (!dateStr || !dateStr.trim()) return NaN;
  const d = new Date(dateStr);
  return isNaN(d.getTime()) ? NaN : d.getMonth();
}
