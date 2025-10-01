import { useMemo } from 'react';
import { Session } from '../types/session';
import { formatTimestamp } from '../utils/datetime';

interface SessionDetailsPanelProps {
  readonly session: Session | null;
}

/**
 * Side panel with detailed session information and embedded snapshot/VNC preview.
 */
export function SessionDetailsPanel({ session }: SessionDetailsPanelProps): JSX.Element {
  const metadataEntries = useMemo(() => {
    if (!session) {
      return [];
    }

    return Object.entries(session.metadata ?? {});
  }, [session]);

  if (!session) {
    return (
      <aside className="session-details">
        <div className="session-details__placeholder">
          <h2>Выберите сессию</h2>
          <p>Данные появятся после выбора карточки.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="session-details">
      <header>
        <h2>{session.browser.name}</h2>
        <span className="session-details__subtitle">{session.browser.version}</span>
      </header>
      <section>
        <dl className="session-details__grid">
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
            <dt>Создана</dt>
            <dd>{formatTimestamp(session.createdAt)}</dd>
          </div>
          <div>
            <dt>Обновлена</dt>
            <dd>{formatTimestamp(session.updatedAt)}</dd>
          </div>
        </dl>
      </section>
      {metadataEntries.length > 0 && (
        <section>
          <h3>Метаданные</h3>
          <ul className="session-details__metadata">
            {metadataEntries.map(([key, value]) => (
              <li key={key}>
                <strong>{key}:</strong> {value}
              </li>
            ))}
          </ul>
        </section>
      )}
      {session.snapshotUrl && (
        <section>
          <h3>Снимок</h3>
          <img src={session.snapshotUrl} alt="Снимок экрана" className="session-details__snapshot" />
        </section>
      )}
      {session.vncUrl && (
        <section>
          <h3>Онлайн доступ</h3>
          <iframe
            title="VNC"
            src={session.vncUrl}
            className="session-details__vnc"
            allow="clipboard-read; clipboard-write"
          />
        </section>
      )}
    </aside>
  );
}
