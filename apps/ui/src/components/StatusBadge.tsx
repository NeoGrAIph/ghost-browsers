import type { SessionStatus } from '../types/session';

const statusColors: Record<SessionStatus, string> = {
  INIT: '#facc15',
  READY: '#34d399',
  TERMINATING: '#fb923c',
  DEAD: '#9ca3af',
};

const statusLabels: Record<SessionStatus, string> = {
  INIT: 'Инициализация',
  READY: 'Готова',
  TERMINATING: 'Завершается',
  DEAD: 'Завершена',
};

interface StatusBadgeProps {
  readonly status: SessionStatus;
}

/**
 * Colored badge reflecting the current session status.
 */
export function StatusBadge({ status }: StatusBadgeProps): JSX.Element {
  return (
    <span className="status-badge" style={{ backgroundColor: statusColors[status] }}>
      {statusLabels[status]}
    </span>
  );
}
