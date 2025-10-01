import type { RunnerStatus } from '../types/runner';

interface WorkerStatusListProps {
  readonly runners: readonly RunnerStatus[];
  readonly isLoading: boolean;
  readonly error: string | null;
}

type IndicatorState = 'healthy' | 'degraded' | 'offline' | 'unknown';

interface IndicatorDescriptor {
  readonly label: string;
  readonly modifier: IndicatorState;
}

const createIndicator = (modifier: IndicatorState, label: string): IndicatorDescriptor => ({
  modifier,
  label,
});

const indicatorForRunner = (runner: RunnerStatus): IndicatorDescriptor => {
  if (!runner.healthy) {
    return createIndicator('offline', 'Недоступен');
  }

  switch (runner.state) {
    case 'idle':
      return createIndicator('healthy', 'Готов');
    case 'busy':
      return createIndicator('degraded', 'Занят');
    case 'starting':
      return createIndicator('degraded', 'Запуск');
    case 'degraded':
      return createIndicator('degraded', 'Проблемы');
    case 'offline':
      return createIndicator('offline', 'Отключён');
    default:
      return createIndicator('unknown', runner.state);
  }
};

const formatSummary = (runner: RunnerStatus, indicator: IndicatorDescriptor) => {
  const parts = [indicator.label];
  if (typeof runner.availableSlots === 'number') {
    parts.push(`Свободно ${runner.availableSlots}`);
  }
  parts.push(runner.supportsVnc ? 'VNC' : 'Без VNC');
  return parts.join(' · ');
};

/**
 * Displays the health status of known runners in a compact list.
 */
export function WorkerStatusList({
  runners,
  isLoading,
  error,
}: WorkerStatusListProps): JSX.Element {
  if (isLoading) {
    return <div className="worker-list__state">Загружаем раннеров…</div>;
  }

  if (error) {
    return <div className="worker-list__state worker-list__state--error">{error}</div>;
  }

  if (!runners.length) {
    return <div className="worker-list__state">Раннеры не найдены</div>;
  }

  return (
    <ul className="worker-list">
      {runners.map((runner) => {
        const indicator = indicatorForRunner(runner);
        const summary = formatSummary(runner, indicator);
        return (
          <li key={runner.id}>
            <span
              className={`worker-status-dot worker-status-dot--${indicator.modifier}`}
              aria-hidden="true"
            />
            <div>
              <strong>{runner.id}</strong>
              <small>{summary}</small>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

