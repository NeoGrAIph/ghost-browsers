/**
 * Utilities for formatting relative times and computing TTL for sessions.
 */

/**
 * Formats the distance between an ISO timestamp and the provided "now" value
 * using the Russian locale. Falls back to the raw string when the input cannot
 * be parsed.
 *
 * @param isoDate - Timestamp of the event in ISO 8601 format.
 * @param now - Milliseconds since epoch used as the reference point.
 * @returns Human friendly relative description (e.g. "5 минут назад").
 */
export const formatRelativeTime = (isoDate: string, now: number): string => {
  const parsed = Date.parse(isoDate);
  if (Number.isNaN(parsed)) {
    return isoDate;
  }

  const safeNow = Number.isFinite(now) ? now : Date.now();
  const diffSeconds = Math.round((parsed - safeNow) / 1000);
  const absoluteSeconds = Math.abs(diffSeconds);

  const formatter = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' });

  if (absoluteSeconds < 60) {
    return formatter.format(Math.round(diffSeconds), 'second');
  }

  const diffMinutes = Math.round(diffSeconds / 60);
  if (Math.abs(diffMinutes) < 60) {
    return formatter.format(diffMinutes, 'minute');
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, 'hour');
  }

  const diffDays = Math.round(diffHours / 24);
  if (Math.abs(diffDays) < 30) {
    return formatter.format(diffDays, 'day');
  }

  const diffMonths = Math.round(diffDays / 30);
  if (Math.abs(diffMonths) < 12) {
    return formatter.format(diffMonths, 'month');
  }

  const diffYears = Math.round(diffMonths / 12);
  return formatter.format(diffYears, 'year');
};

/**
 * Formats duration in seconds as "MM:SS" or "HH:MM:SS" depending on the length.
 *
 * @param seconds - Duration in seconds.
 * @returns Zero padded representation suitable for dashboards.
 */
export const formatDuration = (seconds: number): string => {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainingSeconds = safeSeconds % 60;

  const pad = (value: number) => value.toString().padStart(2, '0');

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(remainingSeconds)}`;
  }

  return `${pad(minutes)}:${pad(remainingSeconds)}`;
};

/**
 * Calculates the remaining idle TTL for a session in seconds.
 *
 * @param lastSeenAt - ISO timestamp of the last heartbeat.
 * @param idleTtlSeconds - Idle TTL configured for the session.
 * @param now - Milliseconds since epoch used as reference for the calculation.
 * @returns Remaining time-to-live in seconds, never below zero.
 */
export const getRemainingIdleSeconds = (
  lastSeenAt: string,
  idleTtlSeconds: number,
  now: number,
): number => {
  const parsed = Date.parse(lastSeenAt);
  if (Number.isNaN(parsed)) {
    return idleTtlSeconds;
  }

  const safeNow = Number.isFinite(now) ? now : Date.now();
  const elapsedSeconds = (safeNow - parsed) / 1000;
  const remaining = idleTtlSeconds - elapsedSeconds;
  return Math.max(0, Math.floor(remaining));
};
