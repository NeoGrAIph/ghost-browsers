import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Topbar } from '../components/Topbar';
import { SessionToolbar } from '../components/SessionToolbar';
import { SessionList } from '../components/SessionList';
import { SessionDetailsPanel } from '../components/SessionDetailsPanel';
import { SessionActions } from '../components/SessionActions';
import { SessionComposer, SessionComposerValues } from '../components/SessionComposer';
import { WorkerStatusList } from '../components/WorkerStatusList';
import { PinnedSessions } from '../components/PinnedSessions';
import { SessionWallboard } from '../components/SessionWallboard';
import { useAuth } from '../hooks/useAuth';
import { fetchSessions, createSession, fetchRunners } from '../api/client';
import { queryKeys } from '../utils/queryKeys';
import { useSessionFilters, type SessionStatusFilter } from '../store/sessionFilters';
import { Session, type SessionStatus } from '../types/session';
import { buildSessionComposerData } from '../utils/composer';
import { useSessionEventConnection } from '../store/sessionEvents';

type MainView = 'sessions' | 'wallboard';

const filterSessions = (
  sessions: Session[],
  search: string,
  status: SessionStatusFilter,
  region: string | null,
  proxyId: string | null,
) => {
  const normalized = search.trim().toLowerCase();
  return sessions.filter((session) => {
    if (status !== 'all' && session.status !== status) {
      return false;
    }

    if (region && session.region !== region) {
      return false;
    }

    if (proxyId && session.proxyId !== proxyId) {
      return false;
    }

    if (!normalized) {
      return true;
    }

    const regionLabel = session.region?.toLowerCase() ?? '';
    const proxyLabel = session.proxyLabel?.toLowerCase() ?? '';
    return (
      session.id.toLowerCase().includes(normalized) ||
      session.runnerId.toLowerCase().includes(normalized) ||
      regionLabel.includes(normalized) ||
      proxyLabel.includes(normalized)
    );
  });
};

/**
 * Dashboard landing page rendered after successful authentication.
 */
export function DashboardPage(): JSX.Element {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const { search, status, region, proxyId } = useSessionFilters();
  const [isComposerOpen, setComposerOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mainView, setMainView] = useState<MainView>('sessions');
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const connectionError = useSessionEventConnection((state) => state.error);
  const requestConnectionRetry = useSessionEventConnection((state) => state.requestRetry);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => fetchSessions({ token: token ?? undefined }),
    refetchInterval: 15_000,
  });

  const sessions = useMemo(() => data ?? [], [data]);
  const sessionsErrorMessage = error
    ? error instanceof Error
      ? error.message
      : 'Не удалось загрузить сессии.'
    : null;

  const {
    data: runners,
    isLoading: isLoadingRunners,
    error: runnerError,
    isFetching: isFetchingRunners,
  } = useQuery({
    queryKey: queryKeys.runners,
    queryFn: () => fetchRunners({ token: token ?? undefined }),
    refetchInterval: 15_000,
  });

  const composerData = useMemo(
    () => buildSessionComposerData(runners ?? [], sessions),
    [runners, sessions],
  );

  const composerError = runnerError instanceof Error ? runnerError.message : null;

  const filteredSessions = useMemo(
    () => filterSessions(sessions, search, status, region, proxyId),
    [sessions, search, status, region, proxyId],
  );

  const selectedSession = filteredSessions.find((session) => session.id === selectedId) ?? null;

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const exists = sessions.some((session) => session.id === selectedId);
    if (!exists) {
      setSelectedId(null);
    }
  }, [sessions, selectedId]);

  useEffect(() => {
    setPinnedIds((current) => {
      const filtered = current.filter((sessionId) =>
        sessions.some((session) => session.id === sessionId && (session.vnc?.httpUrl || session.snapshotUrl)),
      );
      if (filtered.length === current.length && filtered.every((id, index) => id === current[index])) {
        return current;
      }
      return filtered;
    });
  }, [sessions]);

  const pinnedSessions = useMemo(
    () =>
      pinnedIds
        .map((sessionId) => sessions.find((session) => session.id === sessionId) ?? null)
        .filter((session): session is Session => Boolean(session)),
    [pinnedIds, sessions],
  );

  const isPinned = selectedSession ? pinnedIds.includes(selectedSession.id) : false;

  const stats = useMemo(() => {
    const byStatus = new Map<SessionStatus, number>();
    sessions.forEach((session) => {
      const current = byStatus.get(session.status) ?? 0;
      byStatus.set(session.status, current + 1);
    });
    return { total: sessions.length, byStatus };
  }, [sessions]);

  const hasActiveFilters = useMemo(() => {
    if (status !== 'all') {
      return true;
    }
    if (region || proxyId) {
      return true;
    }
    return search.trim().length > 0;
  }, [status, region, proxyId, search]);

  const createMutation = useMutation({
    mutationFn: async (values: SessionComposerValues) => {
      await createSession(
        {
          browserName: values.browserName,
          region: values.region,
          proxyId: values.proxyId,
          runnerId: values.runnerId ?? undefined,
        },
        { token: token ?? undefined },
      );
    },
    onSuccess: () => {
      setComposerOpen(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });

  const handleCreate = async (values: SessionComposerValues) => {
    await createMutation.mutateAsync(values);
  };

  const togglePin = (session: Session) => {
    setPinnedIds((current) => {
      if (current.includes(session.id)) {
        return current.filter((id) => id !== session.id);
      }
      if (!session.vnc?.httpUrl && !session.snapshotUrl) {
        return current;
      }
      return [...current, session.id];
    });
  };

  const removePinned = (sessionId: string) => {
    setPinnedIds((current) => current.filter((id) => id !== sessionId));
  };

  const clearPinned = () => {
    setPinnedIds([]);
  };

  return (
    <div className="dashboard-shell">
      <Topbar />
      {connectionError && (
        <div className="dashboard-banner" role="alert">
          <span>{connectionError}</span>
          <button type="button" onClick={requestConnectionRetry}>
            Повторить
          </button>
        </div>
      )}
      <div className="dashboard-body">
        <aside className="dashboard-sidebar">
          <section className="sidebar-section">
            <h2>Статус кластера</h2>
            <WorkerStatusList
              runners={runners ?? []}
              isLoading={isLoadingRunners}
              error={composerError}
            />
          </section>
          <section className="sidebar-section">
            <h2>Управление</h2>
            <button type="button" className="btn btn-primary" onClick={() => setComposerOpen(true)}>
              Создать сессию
            </button>
            {isFetchingRunners && <span className="sidebar-hint">Обновление справочников…</span>}
          </section>
        </aside>
        <main className="dashboard-main">
          <section className="main-topbar">
            <nav className="main-tabs" aria-label="Основные представления">
              <button
                type="button"
                className={`tab-button${mainView === 'sessions' ? ' tab-button--active' : ''}`}
                onClick={() => setMainView('sessions')}
              >
                Управление
              </button>
              <button
                type="button"
                className={`tab-button${mainView === 'wallboard' ? ' tab-button--active' : ''}`}
                onClick={() => setMainView('wallboard')}
              >
                Стена превью
              </button>
            </nav>
            <div className="topbar-stats">
              <div className="stat">
                <span className="stat-label">Всего</span>
                <span className="stat-value">{stats.total}</span>
              </div>
              {Array.from(stats.byStatus.entries()).map(([entryStatus, count]) => (
                <div key={entryStatus} className="stat">
                  <span className="stat-label">{entryStatus}</span>
                  <span className="stat-value">{count}</span>
                </div>
              ))}
            </div>
          </section>

          <SessionToolbar
            sessions={sessions}
            onCreate={() => setComposerOpen(true)}
            showCreateButton={false}
          />

          {isLoading ? (
            <div className="loading">Загружаем сессии…</div>
          ) : sessionsErrorMessage ? (
            <div className="dashboard-banner dashboard-banner--error" role="alert">
              <span>{sessionsErrorMessage}</span>
              <button
                type="button"
                onClick={() => {
                  void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
                }}
              >
                Повторить
              </button>
            </div>
          ) : mainView === 'sessions' ? (
            <>
              <div className="content-grid">
                <section className="panel">
                  <header className="panel-header">
                    <div>
                      <h2>Сессии</h2>
                      <p>Выберите строку для просмотра деталей и управления.</p>
                    </div>
                  </header>
                  <SessionList
                    sessions={filteredSessions}
                    selectedId={selectedId}
                    onSelect={setSelectedId}
                    now={now}
                    hasActiveFilters={hasActiveFilters}
                  />
                  {isFetching && <div className="loading loading--inline">Обновление…</div>}
                </section>

                <section className="panel">
                  <header className="panel-header">
                    <h2>Инспектор</h2>
                  </header>
                  <SessionDetailsPanel
                    session={selectedSession}
                    now={now}
                    onTogglePin={togglePin}
                    isPinned={isPinned}
                  />
                </section>
              </div>

              <section className="panel">
                <header className="panel-header">
                  <h2>Прокси и управление</h2>
                </header>
                <SessionActions session={selectedSession} />
              </section>

              <PinnedSessions sessions={pinnedSessions} onRemove={removePinned} onClear={clearPinned} />
            </>
          ) : (
            <SessionWallboard
              sessions={sessions}
              now={now}
              onInspect={(session) => {
                setSelectedId(session.id);
                setMainView('sessions');
              }}
            />
          )}
        </main>
      </div>
      {isComposerOpen && (
        <SessionComposer
          onSubmit={handleCreate}
          onCancel={() => setComposerOpen(false)}
          data={composerData}
          isLoading={isLoadingRunners}
          error={composerError}
        />
      )}
    </div>
  );
}
