import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { QueryKey, UseQueryResult } from '@tanstack/react-query';

import { DashboardPage } from '../pages/DashboardPage';
import { App } from '../App';
import { ThemeProvider } from '../providers/ThemeProvider';
import { useSessionFilters } from '../store/sessionFilters';
import { useSessionEventConnection } from '../store/sessionEvents';
import { queryKeys } from '../utils/queryKeys';
import type { Session } from '../types/session';
import type { RunnerStatus } from '../types/runner';

type MockedQueryResult<TData> = Pick<
  UseQueryResult<TData, Error>,
  'data' | 'isLoading' | 'isFetching' | 'error'
>;

const useQueryMock = vi.fn<(options: { queryKey: QueryKey }) => MockedQueryResult<unknown>>();

type MutationOptions = {
  mutationFn: (variables: unknown) => unknown;
  onSuccess?: () => void;
};

type MutationResult = {
  mutate: (value?: unknown) => void;
  mutateAsync: (value?: unknown) => Promise<unknown>;
  isPending: boolean;
};

const useMutationMock = vi.fn<(options: MutationOptions) => MutationResult>();
const invalidateQueriesMock = vi.fn<(options: { queryKey: QueryKey }) => void>();
const setQueryDataMock = vi.fn<(key: QueryKey, data: unknown) => void>();

vi.mock('@tanstack/react-query', () => {
  const module: {
    useQuery: (options: { queryKey: QueryKey }) => MockedQueryResult<unknown>;
    useMutation: (options: MutationOptions) => MutationResult;
    useQueryClient: () => {
      invalidateQueries: (options: { queryKey: QueryKey }) => void;
      setQueryData: (key: QueryKey, data: unknown) => void;
    };
  } = {
    useQuery: (options: { queryKey: QueryKey }) => useQueryMock(options),
    useMutation: (options: MutationOptions) => useMutationMock(options),
    useQueryClient: () => ({ invalidateQueries: invalidateQueriesMock, setQueryData: setQueryDataMock }),
  };
  return module;
});

// Sensible defaults so tests that don't override still work
useQueryMock.mockImplementation(() => ({
  data: [],
  isLoading: false,
  isFetching: false,
  error: null,
}));
useMutationMock.mockImplementation(({ mutationFn, onSuccess }: MutationOptions) => ({
  mutate: (value?: unknown) => {
    const result = mutationFn(value);
    void Promise.resolve(result).then(() => {
      onSuccess?.();
    });
  },
  mutateAsync: async (value?: unknown) => {
    const result = await Promise.resolve(mutationFn(value));
    onSuccess?.();
    return result;
  },
  isPending: false,
}));
invalidateQueriesMock.mockImplementation(() => {});
setQueryDataMock.mockImplementation(() => {});

const {
  fetchSessionsMock,
  fetchRunnersMock,
  createSessionMock,
  deleteSessionMock,
} = vi.hoisted(() => ({
  fetchSessionsMock: vi.fn<(...args: unknown[]) => Promise<Session[]>>(),
  fetchRunnersMock: vi.fn<(...args: unknown[]) => Promise<RunnerStatus[]>>(),
  createSessionMock: vi.fn<(...args: unknown[]) => Promise<Session>>(),
  deleteSessionMock: vi.fn<(...args: unknown[]) => Promise<void>>(),
}));

vi.mock('../api/client', () => ({
  fetchSessions: fetchSessionsMock,
  fetchRunners: fetchRunnersMock,
  createSession: createSessionMock,
  deleteSession: deleteSessionMock,
}));

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    token: 'token-123',
    parsedToken: undefined,
    profile: { firstName: 'Tester' },
    keycloak: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshToken: vi.fn(),
  }),
}));

vi.mock('../components/Topbar', () => ({
  Topbar: () => <div data-testid="topbar" />,
}));

vi.mock('../components/SessionDetailsPanel', () => ({
  SessionDetailsPanel: ({ session }: { session: Session | null }) => (
    <div data-testid="details-panel">{session ? session.id : 'empty'}</div>
  ),
}));

vi.mock('../components/SessionComposer', () => ({
  SessionComposer: ({
    onSubmit,
    onCancel,
    error,
    isLoading,
  }: {
    onSubmit: (values: {
      browserName: string;
      region: string;
      proxyId: string | null;
      runnerId: string | null;
    }) => Promise<void> | void;
    onCancel: () => void;
    error: string | null;
    isLoading: boolean;
  }) => (
    <div data-testid="session-composer">
      {error && <div role="alert">{error}</div>}
      {isLoading && <div>Загружаем доступные параметры…</div>}
      <button
        type="button"
        onClick={() => {
          void onSubmit({ browserName: 'Chrome', region: 'eu', proxyId: null, runnerId: null });
        }}
      >
        Отправить composer
      </button>
      <button type="button" onClick={onCancel}>
        Закрыть composer
      </button>
    </div>
  ),
}));

const createSession = (overrides: Partial<Session>): Session => ({
  id: 'session-id',
  runnerId: 'runner-id',
  status: 'READY',
  createdAt: '2024-09-01T10:00:00.000Z',
  lastSeenAt: '2024-09-01T10:05:00.000Z',
  endedAt: null,
  startUrl: null,
  startUrlWait: 'none',
  headless: false,
  idleTtlSeconds: 60,
  browser: 'Chrome',
  wsEndpoint: null,
  publicWsEndpoint: null,
  proxy: null,
  vnc: null,
  vncEnabled: null,
  labels: {},
  metadata: {},
  region: 'eu',
  proxyId: 'proxy-1',
  proxyLabel: 'Proxy 1',
  snapshotUrl: null,
  ...overrides,
});

const createRunner = (overrides: Partial<RunnerStatus>): RunnerStatus => ({
  id: 'runner-1',
  baseUrl: 'http://runner-1',
  state: 'idle',
  totalSlots: 1,
  availableSlots: 1,
  healthy: true,
  supportsVnc: true,
  lastHeartbeatAt: '2024-09-01T10:00:00.000Z',
  vncHttpUrlTemplate: null,
  vncWsUrlTemplate: null,
  capabilities: [],
  ...overrides,
});

describe('DashboardPage', () => {
  beforeEach(() => {
    useSessionFilters.getState().reset();
    useQueryMock.mockReset();
    useMutationMock.mockReset();
    invalidateQueriesMock.mockReset();
    fetchSessionsMock.mockReset();
    fetchRunnersMock.mockReset();
    createSessionMock.mockReset();
    deleteSessionMock.mockReset();
    useMutationMock.mockImplementation(({ mutationFn, onSuccess }: MutationOptions) => ({
      mutate: (value?: unknown) => {
        const result = mutationFn(value);
        void Promise.resolve(result).then(() => {
          onSuccess?.();
        });
      },
      mutateAsync: async (value?: unknown) => {
        const result = await Promise.resolve(mutationFn(value));
        onSuccess?.();
        return result;
      },
      isPending: false,
    }));
  });

  afterEach(() => {
    cleanup();
  });

  it('shows loading and refreshing states when queries are pending', () => {
    useQueryMock.mockImplementation(({ queryKey }: { queryKey: QueryKey }) => {
      if (queryKey === queryKeys.sessions) {
        return { data: undefined, isLoading: true, isFetching: true, error: undefined };
      }
      if (queryKey === queryKeys.runners) {
        return { data: undefined, isLoading: true, isFetching: true, error: null };
      }
      throw new Error('Unexpected query key');
    });

    render(<DashboardPage />);

    expect(screen.getByText('Загружаем сессии…')).toBeTruthy();
    expect(screen.getAllByText('Обновление…').length).toBe(2);
    expect(screen.getByText('Загружаем раннеров…')).toBeTruthy();
  });

  it('filters sessions based on active store filters', () => {
    const sessions = [
      createSession({ id: 'session-alpha', runnerId: 'runner-alpha', browser: 'Chrome', region: 'eu' }),
      createSession({ id: 'session-beta', runnerId: 'runner-beta', browser: 'Firefox', region: 'us' }),
    ];

    useSessionFilters.setState({
      search: 'beta',
      status: 'all',
      region: null,
      proxyId: null,
    });

    useQueryMock.mockImplementation(({ queryKey }: { queryKey: QueryKey }) => {
      if (queryKey === queryKeys.sessions) {
        return { data: sessions, isLoading: false, isFetching: false, error: undefined };
      }
      if (queryKey === queryKeys.runners) {
        return { data: [createRunner({ id: 'runner-alpha' })], isLoading: false, isFetching: false, error: null };
      }
      throw new Error('Unexpected query key');
    });

    render(<DashboardPage />);

    expect(screen.getByText('session-beta')).toBeTruthy();
    expect(screen.queryByText('session-alpha')).toBeNull();
  });

  it('creates a session through the composer and invalidates the cache', async () => {
    const sessions = [createSession({ id: 'session-alpha' })];

    useQueryMock.mockImplementation(({ queryKey }: { queryKey: QueryKey }) => {
      if (queryKey === queryKeys.sessions) {
        return { data: sessions, isLoading: false, isFetching: false, error: undefined };
      }
      if (queryKey === queryKeys.runners) {
        return { data: [createRunner({ id: 'runner-alpha' })], isLoading: false, isFetching: false, error: null };
      }
      throw new Error('Unexpected query key');
    });

    createSessionMock.mockResolvedValue(createSession({ id: 'session-new' }));

    render(<DashboardPage />);

    fireEvent.click(screen.getByText('Создать сессию'));

    const composer = await screen.findByTestId('session-composer');
    fireEvent.click(within(composer).getByText('Отправить composer'));

    await waitFor(() =>
      expect(createSessionMock).toHaveBeenCalledWith(
        expect.objectContaining({
          browserName: 'Chrome',
          region: 'eu',
          proxyId: null,
          runnerId: undefined,
        }),
        { token: 'token-123' },
      ),
    );

    await waitFor(() => expect(invalidateQueriesMock).toHaveBeenCalledWith({ queryKey: queryKeys.sessions }));
    await waitFor(() => expect(screen.queryByTestId('session-composer')).toBeNull());
  });

  it('deletes the selected session and refreshes the cache', async () => {
    const sessions = [createSession({ id: 'session-alpha', runnerId: 'runner-alpha' })];

    useQueryMock.mockImplementation(({ queryKey }: { queryKey: QueryKey }) => {
      if (queryKey === queryKeys.sessions) {
        return { data: sessions, isLoading: false, isFetching: false, error: undefined };
      }
      if (queryKey === queryKeys.runners) {
        return { data: [createRunner({ id: 'runner-alpha' })], isLoading: false, isFetching: false, error: null };
      }
      throw new Error('Unexpected query key');
    });

    deleteSessionMock.mockResolvedValue(undefined);

    render(<DashboardPage />);

    fireEvent.click(await screen.findByText('session-alpha'));
    fireEvent.click(screen.getByText('Удалить'));

    await waitFor(() => expect(deleteSessionMock).toHaveBeenCalledWith('session-alpha', { token: 'token-123' }));
    await waitFor(() => expect(invalidateQueriesMock).toHaveBeenCalledWith({ queryKey: queryKeys.sessions }));
  });
});

// ---- SSE failure banner tests ----

class MockEventSource {
  public static instances: MockEventSource[] = [];

  public onopen: ((event: Event) => void) | null = null;

  public onmessage: ((event: MessageEvent<string>) => void) | null = null;

  public onerror: ((event: Event) => void) | null = null;

  public readonly close = vi.fn();

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  public constructor(_url: string) {
    MockEventSource.instances.push(this);
    queueMicrotask(() => {
      this.onerror?.(new Event('error'));
    });
  }

  public addEventListener(): void {}

  public removeEventListener(): void {}
}

const originalEventSource = globalThis.EventSource;
const originalSetTimeout = globalThis.setTimeout;
const originalClearTimeout = globalThis.clearTimeout;

const renderApp = () =>
  render(
    <ThemeProvider>
      <App />
    </ThemeProvider>,
  );

describe('DashboardPage SSE failure banner', () => {
  beforeEach(() => {
    // default empty data for queries in App/Dashboard
    useQueryMock.mockReset();
    useQueryMock.mockImplementation(({ queryKey }: { queryKey: QueryKey }) => {
      if (queryKey === queryKeys.sessions) {
        return { data: [], isLoading: false, isFetching: false, error: null };
      }
      if (queryKey === queryKeys.runners) {
        return { data: [], isLoading: false, isFetching: false, error: null };
      }
      return { data: [], isLoading: false, isFetching: false, error: null };
    });

    fetchSessionsMock.mockResolvedValue([]);
    fetchRunnersMock.mockResolvedValue([]);

    MockEventSource.instances = [];
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
    globalThis.setTimeout = ((callback: TimerHandler, delay?: number, ...args: unknown[]) => {
      if (typeof callback === 'function' && typeof delay === 'number' && delay >= 2_000) {
        (callback as (...cbArgs: unknown[]) => void)(...args);
        return 0 as unknown as ReturnType<typeof setTimeout>;
      }
      return originalSetTimeout(callback, delay as number, ...args);
    }) as typeof setTimeout;
    globalThis.clearTimeout = ((handle: ReturnType<typeof setTimeout>) => {
      return originalClearTimeout(handle);
    }) as typeof clearTimeout;
    useSessionEventConnection.getState().reset();
  });

  afterEach(() => {
    cleanup();
    globalThis.EventSource = originalEventSource;
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
  });

  it('displays reconnect banner after exceeding SSE retry limit', async () => {
    renderApp();

    const banner = await screen.findByRole('alert');
    expect(banner.textContent ?? '').toContain('Не удалось подключиться к потоку событий');
    expect(useSessionEventConnection.getState().error).not.toBeNull();

    const previousAttempts = MockEventSource.instances.length;
    expect(previousAttempts).toBeGreaterThanOrEqual(6);
    const retryButton = within(banner).getByRole('button', { name: 'Повторить' });

    act(() => {
      retryButton.click();
    });

    expect(MockEventSource.instances.length).toBeGreaterThan(previousAttempts);

    const bannerAfterRetry = await screen.findByRole('alert');
    expect(bannerAfterRetry.textContent ?? '').toContain(
      'Не удалось подключиться к потоку событий после 5 попыток.',
    );
  });
});
