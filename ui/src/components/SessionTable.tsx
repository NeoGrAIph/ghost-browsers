import type { SessionItem } from '../api';
import { formatStartUrlWait, getStatusBadgeClass, sessionKey } from '../utils/session';
import { formatIdle, formatRelative, remainingIdleSeconds } from '../utils/time';

interface SessionTableProps {
  sessions: SessionItem[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  now: number;
}

export function SessionTable({ sessions, selectedKey, onSelect, now }: SessionTableProps): JSX.Element {
  return (
    <div className="table-wrapper">
      <table className="sessions-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Worker</th>
            <th>Session ID</th>
            <th>Mode</th>
            <th>Last seen</th>
            <th>TTL left</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((session) => {
            const key = sessionKey(session);
            const startUrlWait = session.start_url_wait ?? 'load';
            return (
              <tr
                key={key}
                className={key === selectedKey ? 'selected' : ''}
                onClick={() => onSelect(key)}
              >
                <td>
                  <span className={getStatusBadgeClass(session.status)}>{session.status}</span>
                </td>
                <td>{session.worker}</td>
                <td className="mono">{session.id}</td>
                <td className="table-mode">
                  <span className="pill pill-muted">Camoufox</span>
                  {session.headless ? <span className="pill pill-muted">headless</span> : null}
                  {session.vnc_enabled ? <span className="pill pill-muted">VNC</span> : null}
                  {startUrlWait !== 'load' ? (
                    <span className="pill pill-muted">{formatStartUrlWait(startUrlWait)}</span>
                  ) : null}
                </td>
                <td>{formatRelative(session.last_seen_at)}</td>
                <td>{formatIdle(remainingIdleSeconds(session, now))}</td>
              </tr>
            );
          })}
          {!sessions.length && (
            <tr>
              <td colSpan={6} className="empty">
                There are no sessions yet. Launch one to get started.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
