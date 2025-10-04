import { useMemo } from 'react';
import { Session } from '../types/session';
import { useSessionFilters, SessionStatusFilter } from '../store/sessionFilters';

interface SessionToolbarProps {
  readonly sessions: Session[];
  readonly onCreate: () => void;
  readonly showCreateButton?: boolean;
}

const statusOptions: { readonly value: SessionStatusFilter; readonly label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'INIT', label: 'Инициализация' },
  { value: 'READY', label: 'Готовы' },
  { value: 'TERMINATING', label: 'Завершаются' },
  { value: 'DEAD', label: 'Завершены' },
];

/**
 * Toolbar displayed above the session grid with search and filtering capabilities.
 */
export function SessionToolbar({
  sessions,
  onCreate,
  showCreateButton = true,
}: SessionToolbarProps): JSX.Element {
  const { search, setSearch, status, setStatus, region, setRegion, proxyId, setProxyId, reset } =
    useSessionFilters();

  const regionOptions = useMemo(() => {
    const unique = new Set<string>();
    sessions.forEach((session) => {
      if (session.region) {
        unique.add(session.region);
      }
    });
    return Array.from(unique.values());
  }, [sessions]);

  const proxyOptions = useMemo(() => {
    const unique = new Map<string, string>();
    sessions.forEach((session) => {
      if (session.proxyId) {
        unique.set(session.proxyId, session.proxyLabel ?? session.proxyId);
      }
    });
    return Array.from(unique.entries());
  }, [sessions]);

  return (
    <div className="toolbar">
      <div className="toolbar__search">
        <input
          type="search"
          placeholder="Поиск по ID, региону или прокси"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="toolbar__filters">
        <label>
          Статус
          <select value={status} onChange={(event) => setStatus(event.target.value as SessionStatusFilter)}>
            {statusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Регион
          <select value={region ?? ''} onChange={(event) => setRegion(event.target.value || null)}>
            <option value="">Все</option>
            {regionOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Прокси
          <select value={proxyId ?? ''} onChange={(event) => setProxyId(event.target.value || null)}>
            <option value="">Все</option>
            {proxyOptions.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="ghost" onClick={reset}>
          Сбросить
        </button>
      </div>
      {showCreateButton && (
        <div className="toolbar__actions">
          <button type="button" className="primary" onClick={onCreate}>
            Создать сессию
          </button>
        </div>
      )}
    </div>
  );
}
