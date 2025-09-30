import type { WorkerStatus } from '../api';

interface WorkerListProps {
  workers: WorkerStatus[];
}

type WorkerHealthIndicator = {
  label: string;
  className: string;
};

type WorkerHealthState = 'healthy' | 'degraded' | 'offline' | 'unknown';

const HEALTHY_STATUSES = new Set(['ok', 'healthy', 'ready']);
const DEGRADED_STATUSES = new Set([
  'degraded',
  'warning',
  'starting',
  'initialising',
  'initializing',
  'maintenance',
  'pending',
]);
const OFFLINE_STATUSES = new Set([
  'offline',
  'unreachable',
  'error',
  'failed',
  'down',
  'timeout',
  'stopped',
]);

function createIndicator(state: WorkerHealthState, label: string): WorkerHealthIndicator {
  return {
    label,
    className: `worker-status-dot worker-status-dot--${state}`,
  };
}

const DEFAULT_HEALTH = createIndicator('unknown', 'Unknown');

function normaliseStatus(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed.toLowerCase() : null;
}

function formatStatusLabel(status: string): string {
  return status
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function firstNonOkCheck(detail: WorkerStatus['detail'] | undefined): string | null {
  const rawChecks = detail?.checks;
  if (!rawChecks || typeof rawChecks !== 'object' || Array.isArray(rawChecks)) {
    return null;
  }

  for (const value of Object.values(rawChecks as Record<string, unknown>)) {
    const status = normaliseStatus(value);
    if (status && !HEALTHY_STATUSES.has(status) && status !== 'unknown') {
      return status;
    }
  }

  return null;
}

function indicatorFromStatus(status: string): WorkerHealthIndicator {
  if (HEALTHY_STATUSES.has(status)) {
    return createIndicator('healthy', 'Healthy');
  }
  if (OFFLINE_STATUSES.has(status)) {
    return createIndicator('offline', formatStatusLabel(status));
  }
  if (DEGRADED_STATUSES.has(status)) {
    const label = status === 'starting' ? 'Starting' : formatStatusLabel(status);
    return createIndicator('degraded', label);
  }
  if (status === 'unknown') {
    return DEFAULT_HEALTH;
  }
  return createIndicator('unknown', formatStatusLabel(status));
}

function getWorkerHealth(worker: WorkerStatus): WorkerHealthIndicator {
  if (!worker.healthy) {
    return createIndicator('offline', 'Unreachable');
  }

  const statusText = normaliseStatus(worker.detail?.status);
  const checkStatus = firstNonOkCheck(worker.detail);

  if (checkStatus) {
    const state = OFFLINE_STATUSES.has(checkStatus) ? 'offline' : 'degraded';
    return createIndicator(state, formatStatusLabel(checkStatus));
  }

  if (statusText) {
    return indicatorFromStatus(statusText);
  }

  return DEFAULT_HEALTH;
}

export function WorkerList({ workers }: WorkerListProps): JSX.Element {
  if (!workers.length) {
    return (
      <ul className="worker-list">
        <li className="empty">No workers discovered</li>
      </ul>
    );
  }

  return (
    <ul className="worker-list">
      {workers.map((worker) => {
        const { label, className } = getWorkerHealth(worker);
        return (
          <li key={worker.name}>
            <span className={className} aria-hidden="true" />
            <div>
              <strong>{worker.name}</strong>
              <small>
                {label} · {worker.supports_vnc ? 'VNC' : 'No VNC'}
              </small>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
