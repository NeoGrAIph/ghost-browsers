import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import { SessionToolbar } from '../components/SessionToolbar';
import { useSessionFilters } from '../store/sessionFilters';
import type { Session } from '../types/session';

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
  region: 'eu-central-1',
  proxyId: 'proxy-1',
  proxyLabel: 'Proxy 1',
  snapshotUrl: null,
  ...overrides,
});

describe('SessionToolbar', () => {
  beforeEach(() => {
    useSessionFilters.getState().reset();
  });

  afterEach(() => {
    cleanup();
  });

  it('derives filter options from provided sessions', () => {
    const sessions = [
      createSession({ id: 's-1', region: 'eu-west', proxyId: 'proxy-1', proxyLabel: 'Proxy Alpha' }),
      createSession({ id: 's-2', region: 'us-east', proxyId: 'proxy-2', proxyLabel: 'Proxy Beta' }),
      createSession({ id: 's-3', region: 'eu-west', proxyId: 'proxy-2', proxyLabel: 'Proxy Beta' }),
    ];

    render(<SessionToolbar sessions={sessions} onCreate={() => {}} />);

    const regionSelect = screen.getByLabelText('Регион');
    const regionOptions = within(regionSelect).getAllByRole('option').map((option) => option.textContent);
    expect(regionOptions).toEqual(['Все', 'eu-west', 'us-east']);

    const proxySelect = screen.getByLabelText('Прокси');
    const proxyOptions = within(proxySelect).getAllByRole('option').map((option) => option.textContent);
    expect(proxyOptions).toEqual(['Все', 'Proxy Alpha', 'Proxy Beta']);
  });

  it('updates filters and resets them to defaults', () => {
    render(<SessionToolbar sessions={[createSession({})]} onCreate={() => {}} />);

    const searchInput = screen.getByPlaceholderText('Поиск по ID, региону или прокси');
    fireEvent.change(searchInput, { target: { value: 'runner' } });

    const statusSelect = screen.getByLabelText('Статус');
    fireEvent.change(statusSelect, { target: { value: 'READY' } });

    const regionSelect = screen.getByLabelText('Регион');
    fireEvent.change(regionSelect, { target: { value: 'eu-central-1' } });

    const proxySelect = screen.getByLabelText('Прокси');
    fireEvent.change(proxySelect, { target: { value: 'proxy-1' } });

    expect(useSessionFilters.getState()).toMatchObject({
      search: 'runner',
      status: 'READY',
      region: 'eu-central-1',
      proxyId: 'proxy-1',
    });

    fireEvent.click(screen.getByText('Сбросить'));

    expect(useSessionFilters.getState()).toMatchObject({
      search: '',
      status: 'all',
      region: null,
      proxyId: null,
    });
  });

  it('invokes onCreate when create button is clicked', () => {
    const handleCreate = vi.fn();
    render(<SessionToolbar sessions={[createSession({})]} onCreate={handleCreate} />);

    fireEvent.click(screen.getByText('Создать сессию'));

    expect(handleCreate).toHaveBeenCalledTimes(1);
  });
});

