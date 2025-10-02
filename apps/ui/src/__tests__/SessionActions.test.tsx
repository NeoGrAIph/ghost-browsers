import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { SessionActions } from '../components/SessionActions';
import { queryKeys } from '../utils/queryKeys';
import type { Session } from '../types/session';

type ApiClientModule = typeof import('../api/client');

const apiClientMocks = vi.hoisted(() => ({
  deleteSession: vi.fn<
    ReturnType<ApiClientModule['deleteSession']>,
    Parameters<ApiClientModule['deleteSession']>
  >(),
  updateSessionProxy: vi.fn<
    ReturnType<ApiClientModule['updateSessionProxy']>,
    Parameters<ApiClientModule['updateSessionProxy']>
  >(),
}));

const { deleteSession, updateSessionProxy } = apiClientMocks;

vi.mock('../api/client', () => apiClientMocks);

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ token: 'token-123' }),
}));

const renderWithClient = (ui: JSX.Element, queryClient: QueryClient) =>
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);

const sampleSession = (overrides: Partial<Session> = {}): Session => ({
  id: 'session-1',
  runnerId: 'runner-1',
  status: 'INIT',
  createdAt: new Date().toISOString(),
  lastSeenAt: new Date().toISOString(),
  endedAt: null,
  startUrl: null,
  startUrlWait: 'load',
  headless: false,
  idleTtlSeconds: 300,
  browser: 'Chrome',
  wsEndpoint: null,
  publicWsEndpoint: null,
  proxy: null,
  vnc: null,
  vncEnabled: null,
  labels: {},
  metadata: {},
  region: null,
  proxyId: null,
  proxyLabel: null,
  snapshotUrl: null,
  ...overrides,
});

describe('SessionActions', () => {
  beforeEach(() => {
    deleteSession.mockReset();
    updateSessionProxy.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('updates proxy configuration and refreshes the cache', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });

    const session = sampleSession({
      id: 'session-proxy',
      proxy: {
        http: 'http://proxy.local:3128',
        https: null,
        socks: null,
      },
      proxyLabel: 'http://proxy.local:3128',
    });

    queryClient.setQueryData(queryKeys.sessions, [session]);

    const updatedSession = {
      ...session,
      proxy: {
        http: 'http://new.proxy:8080',
        https: null,
        socks: null,
      },
      proxyLabel: 'http://new.proxy:8080',
    } satisfies Session;

    updateSessionProxy.mockResolvedValue(updatedSession);

    renderWithClient(<SessionActions session={session} />, queryClient);

    const httpInput = screen.getByLabelText('HTTP прокси');
    fireEvent.change(httpInput, { target: { value: ' http://new.proxy:8080 ' } });

    const httpsInput = screen.getByLabelText('HTTPS прокси');
    fireEvent.change(httpsInput, { target: { value: '   ' } });

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(updateSessionProxy).toHaveBeenCalledWith(
        'session-proxy',
        {
          http: 'http://new.proxy:8080',
          https: null,
          socks: null,
        },
        { token: 'token-123' },
      ),
    );

    await waitFor(() => {
      const cached = queryClient.getQueryData<Session[]>(queryKeys.sessions);
      expect(cached?.find((item) => item.id === 'session-proxy')).toEqual(updatedSession);
    });
  });

  it('shows validation error when no proxy values are provided', async () => {
    const queryClient = new QueryClient();
    const session = sampleSession({ id: 'session-empty' });
    queryClient.setQueryData(queryKeys.sessions, [session]);

    renderWithClient(<SessionActions session={session} />, queryClient);

    const httpInput = screen.getByLabelText('HTTP прокси');
    fireEvent.change(httpInput, { target: { value: '   ' } });

    const httpsInput = screen.getByLabelText('HTTPS прокси');
    fireEvent.change(httpsInput, { target: { value: '' } });

    const socksInput = screen.getByLabelText('SOCKS прокси');
    fireEvent.change(socksInput, { target: { value: '' } });

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(updateSessionProxy).not.toHaveBeenCalled();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Укажите корректные URL и заполните хотя бы одно поле.');
  });
});
