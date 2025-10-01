import { Session } from '../types/session';

const statusColors: Record<Session['status'], string> = {
  pending: '#facc15',
  active: '#34d399',
  failed: '#f87171',
  completed: '#60a5fa',
};

const statusLabels: Record<Session['status'], string> = {
  pending: 'Ожидание',
  active: 'Активна',
  failed: 'Ошибка',
  completed: 'Завершена',
};

interface StatusBadgeProps {
  readonly status: Session['status'];
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
