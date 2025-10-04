import { useMemo } from 'react';
import { Session } from '../types/session';
import { formatDuration, formatRelativeTime, getRemainingIdleSeconds } from '../utils/time';
import { StatusBadge } from './StatusBadge';

interface SessionListProps {
  readonly sessions: Session[];
  readonly selectedId: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly now: number;
  readonly hasActiveFilters: boolean;
}

interface SessionListEmptyProps {
  readonly hasFilters: boolean;
}

const renderModePills = (session: Session): string[] => {
  const pills = [session.browser];
  if (session.headless) {
    pills.push('headless');
  }
  if (session.vncEnabled) {
    pills.push('VNC');
  }
  return pills;
};

/**
 * Renders the session catalogue as an accessible data table similar to Camofleet.
 */
export function SessionList({
  sessions,
  selectedId,
  onSelect,
  now,
  hasActiveFilters,
}: SessionListProps): JSX.Element {
  if (!sessions.length) {
    return <SessionListEmpty hasFilters={hasActiveFilters} />;
  }

  return (
    <div className="table-wrapper" role="region" aria-label="Список сессий">
      <table className="sessions-table">
        <thead>
          <tr>
            <th scope="col">Статус</th>
            <th scope="col">Раннер</th>
            <th scope="col">Сессия</th>
            <th scope="col">Режим</th>
            <th scope="col">Последняя активность</th>
            <th scope="col">TTL</th>
            <th scope="col" aria-label="Открыть детали" />
          </tr>
        </thead>
        <tbody>
          {sessions.map((session) => {
            const isSelected = session.id === selectedId;
            const pills = renderModePills(session);
            const ttl = getRemainingIdleSeconds(session.lastSeenAt, session.idleTtlSeconds, now);
            return (
              <tr key={session.id} className={isSelected ? 'selected' : undefined}>
                <td data-title="Статус">
                  <StatusBadge status={session.status} />
                </td>
                <td data-title="Раннер">{session.runnerId}</td>
                <td data-title="Сессия" className="mono">
                  {session.id}
                </td>
                <td data-title="Режим">
                  <div className="pill-group" aria-label="Характеристики режима">
                    {pills.map((label) => (
                      <span key={label} className="pill pill-muted">
                        {label}
                      </span>
                    ))}
                  </div>
                </td>
                <td data-title="Последняя активность">{formatRelativeTime(session.lastSeenAt, now)}</td>
                <td data-title="TTL">{formatDuration(ttl)}</td>
                <td className="sessions-table__actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => onSelect(session.id)}
                    aria-pressed={isSelected}
                    aria-label={`Открыть детали сессии ${session.id}`}
                  >
                    {isSelected ? 'Выбрано' : 'Открыть'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Empty state used when no sessions match the current filters.
 */
function SessionListEmpty({ hasFilters }: SessionListEmptyProps): JSX.Element {
  const message = useMemo(() => {
    if (hasFilters) {
      return {
        title: 'Нет сессий по заданным фильтрам',
        description: 'Измените параметры поиска или запустите новую сессию.',
      };
    }
    return {
      title: 'Сессий пока нет',
      description: 'Создайте новую браузерную сессию, чтобы начать работу.',
    };
  }, [hasFilters]);

  return (
    <div className="empty-state" role="status">
      <h2>{message.title}</h2>
      <p>{message.description}</p>
    </div>
  );
}
