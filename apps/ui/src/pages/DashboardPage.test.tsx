import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { DashboardPage } from './DashboardPage';
import { queryKeys } from '../utils/queryKeys';
import type { Session } from '../types/session';
import { ThemeProvider } from '../providers/ThemeProvider';

const fetchSessions = vi.fn();
const createSession = vi.fn();
const deleteSession = vi.fn();

vi.mock('../api/client', () => ({
  fetchSessions: (...args: unknown[]) => fetchSessions(...args),
  createSession: (...args: unknown[]) => createSession(...args),
  deleteSession: (...args: unknown[]) => deleteSession(...args),
}));

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ token: 'token-123' }),
}));

const renderWithClient = (ui: JSX.Element, queryClient: QueryClient) =>
  render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </ThemeProvider>,
  );

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

describe('DashboardPage', () => {
  beforeEach(() => {
    fetchSessions.mockReset();
    fetchSessions.mockResolvedValue([]);
    createSession.mockReset();
    deleteSession.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('submits create command and closes the composer modal', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    createSession.mockResolvedValue(sampleSession());

    renderWithClient(<DashboardPage />, queryClient);

    await waitFor(() => expect(fetchSessions).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'Создать сессию' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Регион'), { target: { value: 'us-east' } });
    fireEvent.change(within(dialog).getByLabelText('Прокси (необязательно)'), {
      target: { value: 'proxy-9' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(createSession).toHaveBeenCalledWith(
      {
        browserName: 'Chrome',
        region: 'us-east',
        proxyId: 'proxy-9',
      },
      { token: 'token-123' },
    ));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.sessions });

    queryClient.clear();
  });

  it('issues delete command and invalidates the sessions query', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const session = sampleSession({ id: 'session-delete' });
    fetchSessions.mockResolvedValue([session]);
    deleteSession.mockResolvedValue(undefined);

    renderWithClient(<DashboardPage />, queryClient);

    await waitFor(() => expect(fetchSessions).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole('button', { name: /Chrome/i }));
    await waitFor(() =>
      screen
        .getAllByRole('button', { name: 'Удалить' })
        .some((button) => !button.hasAttribute('disabled')),
    );
    const deleteButton = screen
      .getAllByRole('button', { name: 'Удалить' })
      .find((button) => !button.hasAttribute('disabled'))!;
    fireEvent.click(deleteButton);

    await waitFor(() => expect(deleteSession).toHaveBeenCalledWith('session-delete', { token: 'token-123' }));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.sessions });

    queryClient.clear();
  });
});
