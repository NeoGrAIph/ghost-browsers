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
            <h3>{session.browser.name}</h3>
            <span className="session-card__subtitle">{session.browser.version}</span>
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
              <dd>{session.region}</dd>
            </div>
            <div>
              <dt>Прокси</dt>
              <dd>{session.proxy?.label ?? '—'}</dd>
            </div>
            <div>
              <dt>Обновлено</dt>
              <dd>{formatTimestamp(session.updatedAt)}</dd>
            </div>
          </dl>
        </div>
      </button>
    </li>
  );
}
