import { formatTimestamp } from '../utils/datetime';
import { Session } from '../types/session';
import { StatusBadge } from './StatusBadge';

interface SessionListItemProps {
  readonly session: Session;
  readonly isActive: boolean;
  readonly onSelect: () => void;
}

/**
 * Individual card in the session grid.
 */
export function SessionListItem({ session, isActive, onSelect }: SessionListItemProps): JSX.Element {
  const regionLabel = session.region ?? '—';
  const proxyLabel =
    session.proxyLabel ?? session.proxy?.http ?? session.proxy?.https ?? session.proxy?.socks ?? '—';

  return (
    <li>
      <button
        type="button"
        className={`session-card${isActive ? ' session-card--active' : ''}`}
        onClick={onSelect}
        aria-pressed={isActive}
      >
        <div className="session-card__header">
          <div>
            <h3>{session.browser}</h3>
            <span className="session-card__subtitle">{session.runnerId}</span>
          </div>
          <StatusBadge status={session.status} />
        </div>
        <div className="session-card__body">
          <dl>
            <div>
              <dt>ID</dt>
              <dd>{session.id}</dd>
            </div>
            <div>
              <dt>Регион</dt>
              <dd>{regionLabel}</dd>
            </div>
            <div>
              <dt>Прокси</dt>
              <dd>{proxyLabel}</dd>
            </div>
            <div>
              <dt>Обновлено</dt>
              <dd>{formatTimestamp(session.lastSeenAt)}</dd>
            </div>
          </dl>
        </div>
      </button>
    </li>
  );
}
