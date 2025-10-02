import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, within } from '@testing-library/react';

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(() => ({
    data: [],
    isLoading: false,
    isFetching: false,
    error: null,
  })),
  useMutation: vi.fn(() => ({
    mutateAsync: vi.fn(() => Promise.resolve()),
  })),
  useQueryClient: vi.fn(() => ({
    setQueryData: vi.fn(),
    invalidateQueries: vi.fn(),
  })),
}));

import { App } from '../App';
import { ThemeProvider } from '../providers/ThemeProvider';
import { useSessionEventConnection } from '../store/sessionEvents';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    token: 'test-token',
    parsedToken: undefined,
    profile: null,
    keycloak: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshToken: vi.fn(),
  }),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchSessions: vi.fn().mockResolvedValue([]),
    fetchRunners: vi.fn().mockResolvedValue([]),
  };
});

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
