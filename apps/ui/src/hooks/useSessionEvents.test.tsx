import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useSessionEvents } from './useSessionEvents';
import { queryKeys } from '../utils/queryKeys';
import type { Session, SessionEvent } from '../types/session';

interface CapturedEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: ((event: Event) => void) | null;
  onopen: ((event: Event) => void) | null;
  close: ReturnType<typeof vi.fn>;
  url: string;
}

const createdStreams: CapturedEventSource[] = [];

class MockEventSource {
  public onmessage: ((event: MessageEvent<string>) => void) | null = null;
  public onerror: ((event: Event) => void) | null = null;
  public onopen: ((event: Event) => void) | null = null;
  public readonly close = vi.fn();
  public readonly url: string;

  public constructor(url: string | URL) {
    this.url = url instanceof URL ? url.toString() : url;
    createdStreams.push(this);
  }
}

const originalEventSource = globalThis.EventSource;

let sessionCounter = 0;

const createSession = (overrides: Partial<Session> = {}): Session => ({
  id: overrides.id ?? `session-${sessionCounter++}`,
  status: overrides.status ?? 'active',
  createdAt: overrides.createdAt ?? '2025-10-01T00:00:00.000Z',
  updatedAt: overrides.updatedAt ?? '2025-10-01T00:00:00.000Z',
  region: overrides.region ?? 'eu-central',
  proxy: overrides.proxy ?? null,
  browser: overrides.browser ?? { name: 'camoufox', version: '1.0.0' },
  snapshotUrl: overrides.snapshotUrl ?? null,
  vncUrl: overrides.vncUrl ?? null,
  metadata: overrides.metadata ?? {},
});

const renderWithClient = (client: QueryClient, token?: string) =>
  renderHook(() => useSessionEvents({ enabled: true, token }), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });

describe('useSessionEvents', () => {
  beforeEach(() => {
    createdStreams.length = 0;
    sessionCounter = 0;
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalEventSource) {
      globalThis.EventSource = originalEventSource;
    } else {
      // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- test cleanup
      delete (globalThis as Record<string, unknown>).EventSource;
    }
  });

  it('prepends new sessions on session.created events', () => {
    const queryClient = new QueryClient();
    const existing = createSession({ id: 'existing' });
    queryClient.setQueryData<Session[]>(queryKeys.sessions, [existing]);

    const hook = renderWithClient(queryClient, 'token-1');

    const stream = createdStreams.at(-1);
    expect(stream).toBeDefined();
    expect(stream?.url).toContain('access_token=token-1');

    const created = createSession({ id: 'new-session', status: 'pending' });
    const event: SessionEvent = {
      id: '00000000-0000-0000-0000-000000000001',
      type: 'session.created',
      occurredAt: '2025-10-01T00:00:01.000Z',
      reason: null,
      session: created,
    };

    act(() => {
      stream?.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
    });

    const sessions = queryClient.getQueryData<Session[]>(queryKeys.sessions);
    expect(sessions).toHaveLength(2);
    expect(sessions?.[0].id).toBe('new-session');
    expect(sessions?.[1].id).toBe('existing');

    hook.unmount();
    queryClient.clear();
  });

  it('updates existing sessions on session.updated events', () => {
    const queryClient = new QueryClient();
    const existing = createSession({ id: 'session-1', status: 'pending' });
    queryClient.setQueryData<Session[]>(queryKeys.sessions, [existing]);

    const hook = renderWithClient(queryClient);
    const stream = createdStreams.at(-1);
    expect(stream).toBeDefined();

    const updated = { ...existing, status: 'active', updatedAt: '2025-10-01T00:10:00.000Z' } as Session;
    const event: SessionEvent = {
      id: '00000000-0000-0000-0000-000000000002',
      type: 'session.updated',
      occurredAt: '2025-10-01T00:10:00.000Z',
      reason: null,
      session: updated,
    };

    act(() => {
      stream?.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
    });

    const sessions = queryClient.getQueryData<Session[]>(queryKeys.sessions);
    expect(sessions).toHaveLength(1);
    expect(sessions?.[0].status).toBe('active');
    expect(sessions?.[0].updatedAt).toBe('2025-10-01T00:10:00.000Z');

    hook.unmount();
    queryClient.clear();
  });

  it('removes sessions on session.ended events', () => {
    const queryClient = new QueryClient();
    const first = createSession({ id: 'session-a' });
    const second = createSession({ id: 'session-b' });
    queryClient.setQueryData<Session[]>(queryKeys.sessions, [first, second]);

    const hook = renderWithClient(queryClient);
    const stream = createdStreams.at(-1);
    expect(stream).toBeDefined();

    const event: SessionEvent = {
      id: '00000000-0000-0000-0000-000000000003',
      type: 'session.ended',
      occurredAt: '2025-10-01T00:15:00.000Z',
      reason: 'completed',
      session: first,
    };

    act(() => {
      stream?.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
    });

    const sessions = queryClient.getQueryData<Session[]>(queryKeys.sessions);
    expect(sessions).toHaveLength(1);
    expect(sessions?.[0].id).toBe('session-b');

    hook.unmount();
    queryClient.clear();
  });

  it('reconnects with exponential backoff on failures', () => {
    vi.useFakeTimers();
    const timeoutSpy = vi.spyOn(window, 'setTimeout');
    const queryClient = new QueryClient();
    queryClient.setQueryData<Session[]>(queryKeys.sessions, []);

    const hook = renderWithClient(queryClient, 'token-2');
    const first = createdStreams.at(-1);
    expect(first).toBeDefined();

    act(() => {
      first?.onerror?.(new Event('error'));
    });

    expect(first?.close).toHaveBeenCalledTimes(1);
    const initialTimerCalls = timeoutSpy.mock.calls.length;
    expect(initialTimerCalls).toBeGreaterThan(0);
    const firstDelay = timeoutSpy.mock.calls[initialTimerCalls - 1]?.[1] as number;
    expect(firstDelay).toBe(2_000);

    vi.advanceTimersByTime(2_000);
    expect(createdStreams).toHaveLength(2);

    const second = createdStreams.at(-1);
    act(() => {
      second?.onerror?.(new Event('error'));
    });

    const secondTimerCalls = timeoutSpy.mock.calls.length;
    expect(secondTimerCalls).toBeGreaterThan(initialTimerCalls);
    const secondDelay = timeoutSpy.mock.calls[secondTimerCalls - 1]?.[1] as number;
    expect(secondDelay).toBe(firstDelay * 2);

    hook.unmount();
    queryClient.clear();
    timeoutSpy.mockRestore();
  });
});
