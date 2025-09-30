import { useEffect, useMemo, useState } from 'react';
import type { SessionItem, WorkerStatus } from './api';
import { createSession, deleteSession, fetchSessions, fetchWorkers, touchSession } from './api';
import { LaunchSessionForm, type LaunchSessionFormState } from './components/LaunchSessionForm';
import { PinnedSessions } from './components/PinnedSessions';
import { SessionDetails } from './components/SessionDetails';
import { SessionTable } from './components/SessionTable';
import { SessionWallboard } from './components/SessionWallboard';
import { WorkerList } from './components/WorkerList';
import { sessionKey, type StartUrlWait } from './utils/session';

interface CreateSessionPayload {
  worker?: string;
  headless: boolean;
  idle_ttl_seconds: number;
  start_url?: string;
  start_url_wait: StartUrlWait;
  labels?: Record<string, string>;
  vnc: boolean;
}

type ThemeMode = 'light' | 'dark';

type ActionState = {
  type: 'kill' | 'touch';
  key: string;
} | null;

type MainView = 'sessions' | 'wallboard';

const DEFAULT_FORM: LaunchSessionFormState = {
  worker: undefined,
  headless: false,
  idle: 300,
  startUrl: '',
  labels: '',
  vnc: false,
  startUrlWait: 'load',
};

const START_URL_WAIT_OPTIONS: StartUrlWait[] = ['load', 'domcontentloaded', 'none'];

const THEME_STORAGE_KEY = 'camofleet-ui-theme';

function parseLabels(raw: string): Record<string, string> | undefined {
  const entries = raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((pair) => {
      const [key, ...rest] = pair.split('=');
      if (!key) return null;
      return [key.trim(), rest.join('=').trim()] as const;
    })
    .filter((entry): entry is readonly [string, string] => Boolean(entry && entry[0]));
  if (!entries.length) return undefined;
  return Object.fromEntries(entries);
}

function getInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'light';
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY) as ThemeMode | null;
  if (stored === 'dark' || stored === 'light') return stored;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function App(): JSX.Element {
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme);
  const [workers, setWorkers] = useState<WorkerStatus[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [form, setForm] = useState<LaunchSessionFormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<ActionState>(null);
  const [now, setNow] = useState(() => Date.now());
  const [mainView, setMainView] = useState<MainView>('sessions');
  const [pinnedKeys, setPinnedKeys] = useState<string[]>([]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  useEffect(() => {
    const load = async () => {
      try {
        const [workerData, sessionData] = await Promise.all([
          fetchWorkers(),
          fetchSessions(),
        ]);
        setWorkers(workerData);
        setSessions(sessionData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    load();
    // Update worker/session lists via REST polling every 5 seconds.
    const interval = window.setInterval(load, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (selectedKey && !sessions.some((item) => sessionKey(item) === selectedKey)) {
      setSelectedKey(null);
    }
  }, [sessions, selectedKey]);

  useEffect(() => {
    setPinnedKeys((prev) => {
      const next = prev.filter((key) =>
        sessions.some((item) => sessionKey(item) === key && Boolean(item.vnc?.http)),
      );
      return next.length === prev.length ? prev : next;
    });
  }, [sessions]);

  const healthyWorkers = useMemo(
    () => workers.filter((worker) => worker.healthy),
    [workers],
  );

  const selectableWorkerNames = useMemo(
    () =>
      healthyWorkers
        .filter((worker) => !form.vnc || worker.supports_vnc)
        .map((worker) => worker.name),
    [healthyWorkers, form.vnc],
  );

  useEffect(() => {
    if (!form.worker) return;
    if (selectableWorkerNames.includes(form.worker)) return;
    setForm((prev) => ({ ...prev, worker: undefined }));
  }, [form.worker, selectableWorkerNames]);

  const selectedSession = useMemo(
    () => sessions.find((item) => sessionKey(item) === selectedKey) ?? null,
    [sessions, selectedKey],
  );

  const selectedSessionKey = useMemo(
    () => (selectedSession ? sessionKey(selectedSession) : null),
    [selectedSession],
  );

  const pinnedSessions = useMemo(
    () =>
      pinnedKeys
        .map((key) => sessions.find((item) => sessionKey(item) === key) ?? null)
        .filter((item): item is SessionItem => Boolean(item && item.vnc?.http)),
    [pinnedKeys, sessions],
  );

  const isPinned = useMemo(
    () => (selectedSessionKey ? pinnedKeys.includes(selectedSessionKey) : false),
    [pinnedKeys, selectedSessionKey],
  );

  const stats = useMemo(() => {
    const summary = sessions.reduce(
      (acc, session) => {
        acc.total += 1;
        acc.byStatus.set(session.status, (acc.byStatus.get(session.status) ?? 0) + 1);
        return acc;
      },
      { total: 0, byStatus: new Map<string, number>() },
    );
    return summary;
  }, [sessions]);

  const handleFormChange = (patch: Partial<LaunchSessionFormState>) => {
    setForm((prev) => ({ ...prev, ...patch }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const labels = parseLabels(form.labels);
      const payload: CreateSessionPayload = {
        worker: form.worker || undefined,
        headless: form.headless,
        idle_ttl_seconds: form.idle,
        start_url: form.startUrl === '' ? undefined : form.startUrl,
        start_url_wait: form.startUrlWait,
        labels,
        vnc: form.vnc,
      };
      const created = await createSession(payload);
      setSessions((prev) => [
        created,
        ...prev.filter((item) => sessionKey(item) !== sessionKey(created)),
      ]);
      setSelectedKey(sessionKey(created));
      setForm((prev) => ({ ...prev, startUrl: '', labels: '' }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleKill = async (session: SessionItem) => {
    const key = sessionKey(session);
    setActionState({ type: 'kill', key });
    setError(null);
    try {
      await deleteSession(session.worker, session.id);
      setSessions((prev) => prev.filter((item) => sessionKey(item) !== key));
      if (selectedKey === key) {
        setSelectedKey(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionState(null);
    }
  };

  const handleTouch = async (session: SessionItem) => {
    const key = sessionKey(session);
    setActionState({ type: 'touch', key });
    setError(null);
    try {
      const refreshed = await touchSession(session.worker, session.id);
      setSessions((prev) => [
        refreshed,
        ...prev.filter((item) => sessionKey(item) !== key),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionState(null);
    }
  };

  const actionInFlight = (type: ActionState['type'], session: SessionItem | null) => {
    if (!actionState || !session) return false;
    return actionState.type === type && actionState.key === sessionKey(session);
  };

  const togglePinned = (session: SessionItem) => {
    const key = sessionKey(session);
    setPinnedKeys((prev) => {
      if (prev.includes(key)) {
        return prev.filter((item) => item !== key);
      }
      if (!session.vnc?.http) {
        return prev;
      }
      return [...prev, key];
    });
  };

  const removePinned = (key: string) => {
    setPinnedKeys((prev) => prev.filter((item) => item !== key));
  };

  const clearPinned = () => {
    setPinnedKeys([]);
  };

  const onThemeToggle = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));

  const handleCopyWs = (endpoint: string) => {
    if (!navigator.clipboard) {
      setError('Clipboard API is not available in this browser.');
      return;
    }
    navigator.clipboard
      .writeText(endpoint)
      .then(() => setError(null))
      .catch((err) =>
        setError(err instanceof Error ? `Failed to copy: ${err.message}` : 'Failed to copy endpoint'),
      );
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <header className="sidebar-header">
          <div>
            <h1>Camofleet UI</h1>
            <p className="subtitle">Camofleet control panel</p>
          </div>
          <button className="btn btn-ghost" type="button" onClick={onThemeToggle}>
            {theme === 'dark' ? '☀️ Light mode' : '🌙 Dark mode'}
          </button>
        </header>

        <section className="sidebar-section">
          <h2>Cluster status</h2>
          <WorkerList workers={workers} />
        </section>

        <section className="sidebar-section">
          <h2>Launch session</h2>
          <LaunchSessionForm
            form={form}
            healthyWorkers={healthyWorkers}
            loading={loading}
            error={error}
            startUrlWaitOptions={START_URL_WAIT_OPTIONS}
            onChange={handleFormChange}
            onSubmit={handleSubmit}
          />
        </section>
      </aside>

      <main className="main">
        <section className="topbar">
          <nav className="main-tabs" aria-label="Main views">
            <button
              type="button"
              className={`tab-button${mainView === 'sessions' ? ' tab-button--active' : ''}`}
              onClick={() => setMainView('sessions')}
            >
              Manage sessions
            </button>
            <button
              type="button"
              className={`tab-button${mainView === 'wallboard' ? ' tab-button--active' : ''}`}
              onClick={() => setMainView('wallboard')}
            >
              Session wall
            </button>
          </nav>

          <div className="topbar-stats">
            <div className="stat">
              <span className="stat-label">Total</span>
              <span className="stat-value">{stats.total}</span>
            </div>
            {Array.from(stats.byStatus.entries()).map(([status, count]) => (
              <div key={status} className="stat">
                <span className="stat-label">{status}</span>
                <span className="stat-value">{count}</span>
              </div>
            ))}
          </div>
        </section>

        {mainView === 'sessions' ? (
          <>
            <div className="content-grid">
              <section className="panel">
                <header className="panel-header">
                  <div>
                    <h2>Sessions</h2>
                    <p>{sessions.length ? 'Select a session to manage it' : 'No active sessions'}</p>
                  </div>
                </header>
                <SessionTable
                  sessions={sessions}
                  selectedKey={selectedKey}
                  onSelect={setSelectedKey}
                  now={now}
                />
              </section>

              <section className="panel">
                <header className="panel-header">
                  <h2>Inspector</h2>
                </header>
                {selectedSession ? (
                  <SessionDetails
                    session={selectedSession}
                    now={now}
                    iframeKey={selectedSessionKey ?? 'no-session'}
                    onTouch={() => handleTouch(selectedSession)}
                    onKill={() => handleKill(selectedSession)}
                    onCopyWs={handleCopyWs}
                    onTogglePin={() => togglePinned(selectedSession)}
                    isPinned={isPinned}
                    isTouching={actionInFlight('touch', selectedSession)}
                    isKilling={actionInFlight('kill', selectedSession)}
                  />
                ) : (
                  <div className="empty-state">
                    <p>Select a session to inspect details, control TTL, or open the live browser.</p>
                  </div>
                )}
              </section>
            </div>

            {pinnedSessions.length ? (
              <PinnedSessions
                sessions={pinnedSessions}
                onRemove={removePinned}
                onClear={clearPinned}
              />
            ) : null}
          </>
        ) : (
          <SessionWallboard
            sessions={sessions}
            now={now}
            onInspect={(session) => {
              setSelectedKey(sessionKey(session));
              setMainView('sessions');
            }}
          />
        )}
      </main>
    </div>
  );
}
