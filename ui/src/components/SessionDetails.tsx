import type { SessionItem } from '../api';
import { formatStartUrlWait, getStatusBadgeClass } from '../utils/session';
import { formatIdle, formatRelative, remainingIdleSeconds } from '../utils/time';
import { buildVncEmbedUrl, buildVncViewerUrl } from '../utils/vnc';
import { SessionControls } from './SessionControls';

interface SessionDetailsProps {
  session: SessionItem;
  now: number;
  iframeKey: string;
  onTouch: () => void;
  onKill: () => void;
  onCopyWs: (endpoint: string) => void;
  onTogglePin: () => void;
  isPinned: boolean;
  isTouching: boolean;
  isKilling: boolean;
}

export function SessionDetails({
  session,
  now,
  iframeKey,
  onTouch,
  onKill,
  onCopyWs,
  onTogglePin,
  isPinned,
  isTouching,
  isKilling,
}: SessionDetailsProps): JSX.Element {
  const remainingTtl = remainingIdleSeconds(session, now);
  const labels = session.labels || {};
  const hasLabels = Object.keys(labels).length > 0;

  return (
    <div className="session-details">
      <div className="details-header">
        <div>
          <h3 className="mono">{session.id}</h3>
          <p>
            Worker <strong>{session.worker}</strong> · Camoufox{' '}
            {session.headless ? <span className="pill pill-muted">headless</span> : null}{' '}
            {session.vnc_enabled ? <span className="pill pill-muted">VNC</span> : null}
          </p>
        </div>
        <SessionControls
          onTouch={onTouch}
          onKill={onKill}
          isTouching={isTouching}
          isKilling={isKilling}
        />
      </div>

      <dl className="details-list">
        <div>
          <dt>Status</dt>
          <dd>
            <span className={getStatusBadgeClass(session.status)}>{session.status}</span>
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{new Date(session.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Last activity</dt>
          <dd>{formatRelative(session.last_seen_at)}</dd>
        </div>
        <div>
          <dt>TTL left</dt>
          <dd>{formatIdle(remainingTtl)}</dd>
        </div>
        <div>
          <dt>Start URL wait</dt>
          <dd>{formatStartUrlWait(session.start_url_wait ?? 'load')}</dd>
        </div>
        <div>
          <dt>WebSocket endpoint</dt>
          <dd>
            <button className="btn btn-link" type="button" onClick={() => onCopyWs(session.ws_endpoint)}>
              Copy
            </button>
            <code>{session.ws_endpoint}</code>
          </dd>
        </div>
        <div>
          <dt>Labels</dt>
          <dd>
            {hasLabels ? (
              <div className="labels">
                {Object.entries(labels).map(([key, value]) => (
                  <span key={key} className="pill pill-muted">
                    {key}: {value}
                  </span>
                ))}
              </div>
            ) : (
              <span className="pill pill-muted">None</span>
            )}
          </dd>
        </div>
      </dl>

      <div className="vnc-wrapper">
        <div className="vnc-header">
          <h4>Live browser</h4>
          <div className="actions">
            {session.vnc?.http ? (
              <button className="btn btn-secondary" type="button" onClick={onTogglePin}>
                {isPinned ? 'Unpin preview' : 'Pin preview'}
              </button>
            ) : null}
            {session.vnc?.http ? (
              <a
                className="btn btn-secondary"
                href={buildVncViewerUrl(session.vnc.http) ?? session.vnc.http}
                target="_blank"
                rel="noreferrer"
              >
                Open full screen
              </a>
            ) : null}
            {session.vnc?.ws ? (
              <a className="btn btn-secondary" href={session.vnc.ws} target="_blank" rel="noreferrer">
                Raw VNC WS
              </a>
            ) : null}
          </div>
        </div>
        {session.vnc?.http ? (
          <iframe
            title="Browser session"
            key={iframeKey}
            src={buildVncEmbedUrl(session.vnc.http) ?? undefined}
            className="vnc-frame"
          />
        ) : (
          <div className="empty">VNC is not available for this session.</div>
        )}
      </div>
    </div>
  );
}
