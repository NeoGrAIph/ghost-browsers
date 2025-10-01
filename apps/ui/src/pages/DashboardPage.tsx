import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Topbar } from '../components/Topbar';
import { SessionToolbar } from '../components/SessionToolbar';
import { SessionList } from '../components/SessionList';
import { SessionDetailsPanel } from '../components/SessionDetailsPanel';
import { SessionActions } from '../components/SessionActions';
import { SessionComposer, SessionComposerValues } from '../components/SessionComposer';
import { useAuth } from '../hooks/useAuth';
import { fetchSessions, createSession } from '../api/client';
import { buildSessionCreatePayload } from '../api/sessionCreation';
import { queryKeys } from '../utils/queryKeys';
import { useSessionFilters, type SessionStatusFilter } from '../store/sessionFilters';
import { Session } from '../types/session';

const EMPTY_SESSIONS: Session[] = [];

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

    if (proxyId && session.proxy?.id !== proxyId) {
      return false;
    }

    if (!normalized) {
      return true;
    }

    const proxyLabel = session.proxy?.label?.toLowerCase() ?? '';
    return (
      session.id.toLowerCase().includes(normalized) ||
      session.region.toLowerCase().includes(normalized) ||
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

  const { data, isLoading, isFetching } = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => fetchSessions({ token: token ?? undefined }),
    refetchInterval: 15_000,
  });

  const sessions = data?.sessions ?? EMPTY_SESSIONS;

  const filteredSessions = useMemo(
    () => filterSessions(sessions, search, status, region, proxyId),
    [sessions, search, status, region, proxyId],
  );

  const selectedSession = filteredSessions.find((session) => session.id === selectedId) ?? null;

  const createMutation = useMutation({
    mutationFn: async (values: SessionComposerValues) => {
      const payload = buildSessionCreatePayload(values);
      await createSession(payload, { token: token ?? undefined });
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
          <SessionActions session={selectedSession} />
          <SessionDetailsPanel session={selectedSession} />
        </div>
      </main>
      {isComposerOpen && (
        <SessionComposer onSubmit={handleCreate} onCancel={() => setComposerOpen(false)} />
      )}
    </div>
  );
}
