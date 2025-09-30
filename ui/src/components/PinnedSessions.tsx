import type { SessionItem } from '../api';
import { sessionKey } from '../utils/session';
import { buildVncEmbedUrl } from '../utils/vnc';

interface PinnedSessionsProps {
  sessions: SessionItem[];
  onRemove: (key: string) => void;
  onClear: () => void;
}

export function PinnedSessions({ sessions, onRemove, onClear }: PinnedSessionsProps): JSX.Element {
  return (
    <section className="panel pinned-panel">
      <header className="panel-header pinned-header">
        <div>
          <h2>Pinned sessions</h2>
          <p>Quick access to VNC previews you have pinned.</p>
        </div>
        <button className="btn btn-link" type="button" onClick={onClear}>
          Clear all
        </button>
      </header>

      <div className="pinned-grid">
        {sessions.map((session) => {
          const key = sessionKey(session);
          return (
            <article key={key} className="pinned-card">
              <header className="pinned-card__header">
                <div className="pinned-card__title">
                  <span className="pill pill-muted">{session.worker}</span>
                  <strong className="mono">{session.id}</strong>
                </div>
                <button className="btn btn-ghost" type="button" onClick={() => onRemove(key)}>
                  Remove
                </button>
              </header>
              <iframe
                title={`Pinned session ${session.id}`}
                key={`${key}-pinned`}
                src={buildVncEmbedUrl(session.vnc?.http) ?? undefined}
                className="pinned-frame"
              />
            </article>
          );
        })}
      </div>
    </section>
  );
}
