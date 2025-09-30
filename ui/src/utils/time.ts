export function formatRelative(date: string): string {
  const target = new Date(date).valueOf();
  if (Number.isNaN(target)) return 'unknown';
  const delta = Date.now() - target;
  if (delta < 30_000) return 'just now';
  if (delta < 60_000) return `${Math.round(delta / 1000)}s ago`;
  if (delta < 3_600_000) return `${Math.round(delta / 60_000)}m ago`;
  if (delta < 43_200_000) return `${Math.round(delta / 3_600_000)}h ago`;
  return new Date(date).toLocaleString();
}

export function formatIdle(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—';
  const clamped = Math.max(0, Math.floor(seconds));
  return `${clamped}s`;
}

export function remainingIdleSeconds<
  T extends { last_seen_at: string; idle_ttl_seconds: number }
>(session: T, nowMs: number): number {
  const lastSeen = new Date(session.last_seen_at).valueOf();
  if (Number.isNaN(lastSeen)) {
    return Math.max(0, Math.floor(session.idle_ttl_seconds));
  }
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - lastSeen) / 1000));
  const remaining = Math.floor(session.idle_ttl_seconds - elapsedSeconds);
  return remaining > 0 ? remaining : 0;
}
