import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Topbar } from '../components/Topbar';
import { SessionToolbar } from '../components/SessionToolbar';
import { SessionList } from '../components/SessionList';
import { SessionDetailsPanel } from '../components/SessionDetailsPanel';
import { SessionActions } from '../components/SessionActions';
import { SessionComposer, SessionComposerValues } from '../components/SessionComposer';
import { WorkerStatusList } from '../components/WorkerStatusList';
import { useAuth } from '../hooks/useAuth';
import { fetchSessions, createSession, fetchRunners } from '../api/client';
import { queryKeys } from '../utils/queryKeys';
import { useSessionFilters, type SessionStatusFilter } from '../store/sessionFilters';
import { Session } from '../types/session';
import { buildSessionComposerData } from '../utils/composer';
import { useSessionEventConnection } from '../store/sessionEvents';

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
  const connectionError = useSessionEventConnection((state) => state.error);
  const requestConnectionRetry = useSessionEventConnection((state) => state.requestRetry);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => fetchSessions({ token: token ?? undefined }),
    refetchInterval: 15_000,
  });

  const sessions = useMemo(() => data ?? [], [data]);

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

  return (
    <div className="dashboard">
      <Topbar />
      {connectionError && (
        <div className="dashboard__banner" role="alert">
          <span>{connectionError}</span>
          <button type="button" onClick={requestConnectionRetry}>
            Повторить
          </button>
        </div>
      )}
      <main className="dashboard__content">
        <div className="dashboard__left">
          <SessionToolbar sessions={sessions} onCreate={() => setComposerOpen(true)} />
          {isLoading ? (
            <div className="loading">Загружаем сессии…</div>
          ) : (
            <SessionList sessions={filteredSessions} selectedId={selectedId} onSelect={setSelectedId} />
          )}
          {isFetching && <div className="loading loading--inline">Обновление…</div>}
        </div>
        <div className="dashboard__right">
          <section className="dashboard__panel">
            <header>
              <h3>Статус раннеров</h3>
              {isFetchingRunners && <span className="dashboard__refresh">Обновление…</span>}
            </header>
            <WorkerStatusList
              runners={runners ?? []}
              isLoading={isLoadingRunners}
              error={composerError}
            />
          </section>
          <SessionActions session={selectedSession} />
          <SessionDetailsPanel session={selectedSession} />
        </div>
      </main>
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
