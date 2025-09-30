import { useEffect, useMemo, useState } from 'react';
import type { SessionItem } from '../api';
import { sessionKey } from '../utils/session';
import { formatRelative } from '../utils/time';
import { buildVncEmbedUrl, buildVncViewerUrl } from '../utils/vnc';

const GRID_OPTIONS = [1, 4, 9] as const;

type GridSize = (typeof GRID_OPTIONS)[number];

interface SessionWallboardProps {
  sessions: SessionItem[];
  now: number;
  onInspect: (session: SessionItem) => void;
}

interface FrameState {
  [key: string]: number | undefined;
}

function columnsFor(size: GridSize): number {
  if (size === 1) return 1;
  if (size === 4) return 2;
  if (size === 9) return 3;
  return Math.ceil(Math.sqrt(size));
}

const FAILURE_GRACE_MS = Number(import.meta.env.VITE_WALLBOARD_FAILURE_GRACE_MS ?? 3000);
const RETRY_DELAY_MS = Number(import.meta.env.VITE_WALLBOARD_RETRY_DELAY_MS ?? 10000);

export function SessionWallboard({ sessions, now, onInspect }: SessionWallboardProps): JSX.Element {
  const [gridSize, setGridSize] = useState<GridSize>(4);
  const [page, setPage] = useState(0);
  const [failedAt, setFailedAt] = useState<FrameState>({});

  const sessionsWithVnc = useMemo(
    () => sessions.filter((item) => Boolean(item.vnc?.http)),
    [sessions],
  );

  useEffect(() => {
    const allowedKeys = new Set(sessionsWithVnc.map((session) => sessionKey(session)));
    setFailedAt((prev) => {
      const next: FrameState = {};
      let changed = false;
      for (const [key, ts] of Object.entries(prev)) {
        if (allowedKeys.has(key)) {
          next[key] = ts;
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [sessionsWithVnc]);

  useEffect(() => {
    if (RETRY_DELAY_MS <= 0) return;
    const interval = window.setInterval(() => {
      const limit = Date.now() - (FAILURE_GRACE_MS + RETRY_DELAY_MS);
      setFailedAt((prev) => {
        const next: FrameState = {};
        let changed = false;
        for (const [key, ts] of Object.entries(prev)) {
          if (typeof ts === 'number' && ts > limit) {
            next[key] = ts;
          } else if (typeof ts === 'number') {
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, Math.max(2000, Math.min(10000, RETRY_DELAY_MS)));
    return () => window.clearInterval(interval);
  }, []);

  const { recoveringKeys, blockedKeys } = useMemo(() => {
    const recovering = new Set<string>();
    const blocked = new Set<string>();
    for (const session of sessionsWithVnc) {
      const key = sessionKey(session);
      const failure = failedAt[key];
      if (typeof failure !== 'number') continue;
      const delta = now - failure;
      if (delta < FAILURE_GRACE_MS) {
        recovering.add(key);
      } else {
        blocked.add(key);
      }
    }
    return { recoveringKeys: recovering, blockedKeys: blocked };
  }, [sessionsWithVnc, failedAt, now]);

  const availableSessions = useMemo(
    () => sessionsWithVnc.filter((session) => !blockedKeys.has(sessionKey(session))),
    [sessionsWithVnc, blockedKeys],
  );

  useEffect(() => {
    setPage(0);
  }, [gridSize]);

  const maxPage = Math.max(0, Math.ceil(availableSessions.length / gridSize) - 1);

  useEffect(() => {
    setPage((prev) => (prev > maxPage ? maxPage : prev));
  }, [maxPage]);

  const startIndex = page * gridSize;
  const visibleSessions = availableSessions.slice(startIndex, startIndex + gridSize);
  const placeholders = Math.max(0, gridSize - visibleSessions.length);
  const totalEligible = sessionsWithVnc.length;
  const blockedCount = blockedKeys.size;
  const columns = columnsFor(gridSize);

  const handleFrameError = (key: string) => {
    setFailedAt((prev) => {
      if (typeof prev[key] === 'number') {
        return prev;
      }
      return { ...prev, [key]: Date.now() };
    });
  };

  const handleFrameLoad = (key: string) => {
    setFailedAt((prev) => {
      if (typeof prev[key] !== 'number') {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const hasPrev = page > 0;
  const hasNext = page < maxPage;
  const totalPages = maxPage + 1;

  return (
    <section className="panel wallboard-panel">
      <header className="panel-header wallboard-header">
        <div>
          <h2>Live wallboard</h2>
          <p>
            Showing {visibleSessions.length} of {availableSessions.length} VNC sessions
            {blockedCount ? ` · ${blockedCount} waiting to reconnect` : ''}
          </p>
        </div>
        <div className="wallboard-toolbar">
          <div className="layout-switcher" role="group" aria-label="Grid size">
            {GRID_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className={`tab-button${gridSize === option ? ' tab-button--active' : ''}`}
                onClick={() => setGridSize(option)}
              >
                {option}
              </button>
            ))}
          </div>
          <div className="pager">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((prev) => Math.max(0, prev - 1))}
              disabled={!hasPrev}
            >
              ◀
            </button>
            <span className="pager-info">
              {totalPages > 0 ? `${page + 1} / ${totalPages}` : '0 / 0'}
            </span>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((prev) => Math.min(maxPage, prev + 1))}
              disabled={!hasNext}
            >
              ▶
            </button>
          </div>
        </div>
      </header>

      <div className="wallboard-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
        {visibleSessions.map((session) => {
          const key = sessionKey(session);
          const failure = failedAt[key];
          const isRecovering = recoveringKeys.has(key);
          const remainingMs = typeof failure === 'number' ? Math.max(0, FAILURE_GRACE_MS - (now - failure)) : 0;
          return (
            <article key={key} className={`wallboard-tile${isRecovering ? ' wallboard-tile--recovering' : ''}`}>
              <div className="wallboard-tile__actions" role="group" aria-label="Session shortcuts">
                {session.vnc?.http ? (
                  <a
                    className="wallboard-tile__action"
                    href={buildVncViewerUrl(session.vnc?.http) ?? session.vnc?.http ?? undefined}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    Open VNC
                  </a>
                ) : null}
                <button
                  type="button"
                  className="wallboard-tile__action"
                  onClick={() => onInspect(session)}
                >
                  Inspect
                </button>
              </div>
              <header className="wallboard-tile__header">
                <div className="wallboard-tile__meta">
                  <span className="wallboard-tile__worker">{session.worker}</span>
                  <span className="wallboard-tile__id">{session.id}</span>
                </div>
              </header>
              <iframe
                title={`Session ${session.id}`}
                src={buildVncEmbedUrl(session.vnc?.http) ?? undefined}
                className="wallboard-frame"
                onLoad={() => handleFrameLoad(key)}
                onError={() => handleFrameError(key)}
              />
              <footer className="wallboard-tile__footer">
                <span className="status">{session.status}</span>
                <span className="timestamp">Last activity · {formatRelative(session.last_seen_at)}</span>
              </footer>
              {isRecovering ? (
                <div className="wallboard-tile__overlay">
                  <span>Reconnecting… {Math.ceil(remainingMs / 1000)}s</span>
                </div>
              ) : null}
            </article>
          );
        })}
        {Array.from({ length: placeholders }).map((_, index) => (
          <div key={`placeholder-${index}`} className="wallboard-tile wallboard-tile--placeholder">
            <span>No session</span>
          </div>
        ))}
      </div>

      {totalEligible === 0 ? (
        <div className="wallboard-empty">
          <p>No VNC-enabled sessions are available yet.</p>
        </div>
      ) : null}
      {totalEligible > 0 && availableSessions.length === 0 ? (
        <div className="wallboard-empty">
          <p>All available sessions are temporarily offline. Waiting for reconnect…</p>
        </div>
      ) : null}
    </section>
  );
}
