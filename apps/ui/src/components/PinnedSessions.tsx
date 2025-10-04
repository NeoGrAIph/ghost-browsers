import { Session } from '../types/session';

interface PinnedSessionsProps {
  readonly sessions: Session[];
  readonly onRemove: (sessionId: string) => void;
  readonly onClear: () => void;
}

/**
 * Displays pinned sessions with inline VNC iframes mirroring the Camofleet UX.
 */
export function PinnedSessions({ sessions, onRemove, onClear }: PinnedSessionsProps): JSX.Element {
  if (!sessions.length) {
    return <></>;
  }

  return (
    <section className="panel pinned-panel" aria-label="Закреплённые сессии">
      <header className="panel-header pinned-header">
        <div>
          <h2>Закреплённые сессии</h2>
          <p>Быстрый доступ к важным VNC-превью.</p>
        </div>
        <button type="button" className="btn btn-link" onClick={onClear}>
          Очистить
        </button>
      </header>
      <div className="pinned-grid">
        {sessions.map((session) => (
          <article key={session.id} className="pinned-card">
            <header className="pinned-card__header">
              <div className="pinned-card__title">
                <span className="pill pill-muted">{session.runnerId}</span>
                <strong className="mono">{session.id}</strong>
              </div>
              <button type="button" className="btn btn-ghost" onClick={() => onRemove(session.id)}>
                Удалить
              </button>
            </header>
            {session.vnc?.httpUrl ? (
              <iframe
                title={`VNC ${session.id}`}
                src={session.vnc.httpUrl}
                className="pinned-frame"
                allow="clipboard-read; clipboard-write"
              />
            ) : session.snapshotUrl ? (
              <img src={session.snapshotUrl} alt="Снимок сессии" className="pinned-frame" />
            ) : (
              <div className="pinned-frame pinned-frame--empty">Предпросмотр недоступен</div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
