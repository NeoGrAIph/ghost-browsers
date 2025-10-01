import { Session } from '../types/session';
import { SessionListItem } from './SessionListItem';

interface SessionListProps {
  readonly sessions: Session[];
  readonly selectedId: string | null;
  readonly onSelect: (sessionId: string) => void;
}

/**
 * Renders the session cards grid.
 */
export function SessionList({ sessions, selectedId, onSelect }: SessionListProps): JSX.Element {
  if (!sessions.length) {
    return (
      <div className="empty-state">
        <h2>Сессий пока нет</h2>
        <p>Создайте новую браузерную сессию или измените фильтры.</p>
      </div>
    );
  }

  return (
    <ul className="session-grid">
      {sessions.map((session) => (
        <SessionListItem
          key={session.id}
          session={session}
          isActive={session.id === selectedId}
          onSelect={() => onSelect(session.id)}
        />
      ))}
    </ul>
  );
}
