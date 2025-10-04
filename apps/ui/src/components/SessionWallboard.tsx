import { useMemo, useState } from 'react';
import { Session } from '../types/session';
import { formatRelativeTime } from '../utils/time';

const GRID_OPTIONS = [1, 4, 9] as const;

type GridSize = (typeof GRID_OPTIONS)[number];

interface SessionWallboardProps {
  readonly sessions: Session[];
  readonly now: number;
  readonly onInspect: (session: Session) => void;
}

/**
 * Video wall with VNC previews inspired by Camofleet for quick monitoring.
 */
export function SessionWallboard({ sessions, now, onInspect }: SessionWallboardProps): JSX.Element {
  const [gridSize, setGridSize] = useState<GridSize>(4);
  const [page, setPage] = useState(0);

  const sessionsWithPreview = useMemo(
    () => sessions.filter((session) => Boolean(session.vnc?.httpUrl || session.snapshotUrl)),
    [sessions],
  );

  const maxPage = Math.max(0, Math.ceil(sessionsWithPreview.length / gridSize) - 1);
  const startIndex = page * gridSize;
  const visible = sessionsWithPreview.slice(startIndex, startIndex + gridSize);
  const placeholders = Math.max(0, gridSize - visible.length);
  const columns = Math.sqrt(gridSize);

  return (
    <section className="panel wallboard-panel" aria-label="Стена превью">
      <header className="panel-header wallboard-header">
        <div>
          <h2>Live wallboard</h2>
          <p>
            Показано {visible.length} из {sessionsWithPreview.length} доступных сессий
          </p>
        </div>
        <div className="wallboard-toolbar">
          <div className="layout-switcher" role="group" aria-label="Размер сетки">
            {GRID_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className={`tab-button${gridSize === option ? ' tab-button--active' : ''}`}
                onClick={() => {
                  setGridSize(option);
                  setPage(0);
                }}
              >
                {option}
              </button>
            ))}
          </div>
          <div className="pager">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              disabled={page === 0}
            >
              ◀
            </button>
            <span className="pager-info">{sessionsWithPreview.length ? `${page + 1} / ${maxPage + 1}` : '0 / 0'}</span>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((current) => Math.min(maxPage, current + 1))}
              disabled={page >= maxPage}
            >
              ▶
            </button>
          </div>
        </div>
      </header>

      <div className="wallboard-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
        {visible.map((session) => (
          <article key={session.id} className="wallboard-tile">
            <div className="wallboard-tile__actions" role="group" aria-label="Действия">
              {session.vnc?.httpUrl && (
                <a className="wallboard-tile__action" href={session.vnc.httpUrl} target="_blank" rel="noreferrer">
                  Открыть VNC
                </a>
              )}
              <button type="button" className="wallboard-tile__action" onClick={() => onInspect(session)}>
                Инспектор
              </button>
            </div>
            <header className="wallboard-tile__header">
              <div className="wallboard-tile__meta">
                <span className="wallboard-tile__worker">{session.runnerId}</span>
                <span className="wallboard-tile__id">{session.id}</span>
              </div>
              <span className="wallboard-tile__timestamp">
                {formatRelativeTime(session.lastSeenAt, now)}
              </span>
            </header>
            {session.vnc?.httpUrl ? (
              <iframe
                title={`Session ${session.id}`}
                src={session.vnc.httpUrl}
                className="wallboard-frame"
                allow="clipboard-read; clipboard-write"
              />
            ) : (
              <img src={session.snapshotUrl ?? ''} alt="Снимок сессии" className="wallboard-frame" />
            )}
          </article>
        ))}
        {Array.from({ length: placeholders }).map((_, index) => (
          <div key={index} className="wallboard-tile wallboard-tile--placeholder">
            <span>Свободно</span>
          </div>
        ))}
      </div>

      {!sessionsWithPreview.length && (
        <div className="wallboard-empty">
          <p>Нет сессий с доступным VNC или снимком.</p>
        </div>
      )}
    </section>
  );
}
