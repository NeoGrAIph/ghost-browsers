import { useMemo, useState } from 'react';
import { Session } from '../types/session';
import { formatTimestamp } from '../utils/datetime';
import { formatDuration, formatRelativeTime, getRemainingIdleSeconds } from '../utils/time';
import { StatusBadge } from './StatusBadge';

interface SessionDetailsPanelProps {
  readonly session: Session | null;
  readonly now: number;
  readonly onTogglePin: (session: Session) => void;
  readonly isPinned: boolean;
}

const buildWsEndpoint = (session: Session): string | null =>
  session.wsEndpoint ?? session.publicWsEndpoint ?? null;

/**
 * Detailed inspector replicating the UX of Camofleet with pinning and copy helpers.
 */
export function SessionDetailsPanel({
  session,
  now = Date.now(),
  onTogglePin,
  isPinned,
}: SessionDetailsPanelProps): JSX.Element {
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  const metadataEntries = useMemo(() => {
    if (!session) {
      return [];
    }
    return Object.entries(session.metadata ?? {});
  }, [session]);

  const labelEntries = useMemo(() => {
    if (!session) {
      return [];
    }
    return Object.entries(session.labels ?? {});
  }, [session]);

  if (!session) {
    return (
      <aside className="session-details">
        <div className="session-details__placeholder" role="status">
          <h2>Выберите сессию</h2>
          <p>Информация появится после выбора строки в таблице.</p>
        </div>
      </aside>
    );
  }

  const wsEndpoint = buildWsEndpoint(session);
  const ttl = getRemainingIdleSeconds(session.lastSeenAt, session.idleTtlSeconds, now);
  const vncHttp = session.vnc?.httpUrl ?? null;
  const vncWs = session.vnc?.websocketUrl ?? null;

  const copyWsEndpoint = async () => {
    if (!wsEndpoint) {
      setCopyFeedback('WebSocket недоступен для этой сессии.');
      return;
    }

    if (!navigator.clipboard) {
      setCopyFeedback('Буфер обмена недоступен в этом браузере.');
      return;
    }

    try {
      await navigator.clipboard.writeText(wsEndpoint);
      setCopyFeedback('Ссылка на WebSocket скопирована.');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Неизвестная ошибка';
      setCopyFeedback(`Не удалось скопировать: ${message}`);
    }
  };

  const handleCopyWs = () => {
    void copyWsEndpoint();
  };

  return (
    <aside className="session-details">
      <header className="session-details__header">
        <div>
          <h2 className="mono">{session.id}</h2>
          <p className="session-details__subtitle">{session.runnerId}</p>
        </div>
        <div className="session-details__actions">
          <button type="button" className="btn btn-secondary" onClick={handleCopyWs}>
            Копировать WebSocket
          </button>
          {vncHttp && (
            <button type="button" className="btn btn-secondary" onClick={() => onTogglePin(session)}>
              {isPinned ? 'Открепить превью' : 'Закрепить превью'}
            </button>
          )}
          {vncHttp && (
            <a className="btn btn-secondary" href={vncHttp} target="_blank" rel="noreferrer">
              Открыть VNC
            </a>
          )}
        </div>
      </header>

      <dl className="session-details__grid">
        <div>
          <dt>Статус</dt>
          <dd>
            <StatusBadge status={session.status} />
          </dd>
        </div>
        <div>
          <dt>Создана</dt>
          <dd>{formatTimestamp(session.createdAt)}</dd>
        </div>
        <div>
          <dt>Последняя активность</dt>
          <dd>{formatRelativeTime(session.lastSeenAt, now)}</dd>
        </div>
        <div>
          <dt>TTL</dt>
          <dd>{formatDuration(ttl)}</dd>
        </div>
        <div>
          <dt>Регион</dt>
          <dd>{session.region ?? '—'}</dd>
        </div>
        <div>
          <dt>Прокси</dt>
          <dd>{session.proxyLabel ?? session.proxyId ?? '—'}</dd>
        </div>
        <div>
          <dt>Стартовый URL</dt>
          <dd>{session.startUrl ?? '—'}</dd>
        </div>
        <div>
          <dt>Ожидание загрузки</dt>
          <dd>{session.startUrlWait}</dd>
        </div>
        <div>
          <dt>WebSocket</dt>
          <dd>{wsEndpoint ?? '—'}</dd>
        </div>
      </dl>

      <section className="session-details__section">
        <h3>Метки</h3>
        {labelEntries.length ? (
          <div className="pill-group">
            {labelEntries.map(([key, value]) => (
              <span key={key} className="pill pill-muted">
                {key}: {value}
              </span>
            ))}
          </div>
        ) : (
          <p className="session-details__empty">Метки отсутствуют.</p>
        )}
      </section>

      {metadataEntries.length > 0 && (
        <section className="session-details__section">
          <h3>Метаданные</h3>
          <ul className="session-details__metadata">
            {metadataEntries.map(([key, value]) => (
              <li key={key}>
                <strong>{key}:</strong> {String(value)}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="session-details__section">
        <h3>Онлайн доступ</h3>
        {vncHttp ? (
          <iframe
            title="VNC"
            src={vncHttp}
            className="session-details__vnc"
            allow="clipboard-read; clipboard-write"
          />
        ) : session.snapshotUrl ? (
          <img src={session.snapshotUrl} alt="Снимок экрана" className="session-details__snapshot" />
        ) : (
          <p className="session-details__empty">VNC и снимок отсутствуют.</p>
        )}
        {vncWs && (
          <p className="session-details__hint">WS: {vncWs}</p>
        )}
      </section>

      {copyFeedback && (
        <p role="status" className="session-details__hint">
          {copyFeedback}
        </p>
      )}
    </aside>
  );
}
