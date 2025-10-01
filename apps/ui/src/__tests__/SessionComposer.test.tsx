import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, fireEvent, within } from '@testing-library/react';

import { SessionComposer } from '../components/SessionComposer';
import type { SessionComposerData } from '../utils/composer';

const noop = () => Promise.resolve();

const sampleData = (overrides: Partial<SessionComposerData> = {}): SessionComposerData => ({
  browsers: [{ id: 'Chrome', label: 'Chrome' }],
  regions: [
    { id: 'eu', label: 'eu' },
    { id: 'us', label: 'us' },
  ],
  proxies: [],
  runners: [
    {
      id: 'runner-eu',
      label: 'runner-eu',
      healthy: true,
      supportsVnc: true,
      state: 'idle',
      availableSlots: 1,
      browsers: ['Chrome'],
      regions: ['eu'],
      proxies: [],
    },
    {
      id: 'runner-us',
      label: 'runner-us',
      healthy: true,
      supportsVnc: true,
      state: 'idle',
      availableSlots: 1,
      browsers: ['Chrome'],
      regions: ['us'],
      proxies: [],
    },
  ],
  ...overrides,
});

describe('SessionComposer', () => {
  it('renders loading hint when options are loading', () => {
    render(
      <SessionComposer
        data={null}
        isLoading
        error={null}
        onSubmit={noop}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText('Загружаем доступные параметры…')).toBeTruthy();
  });

  it('displays error message when fetching options fails', () => {
    render(
      <SessionComposer
        data={sampleData()}
        isLoading={false}
        error="Не удалось загрузить раннеров"
        onSubmit={noop}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText('Не удалось загрузить раннеров')).toBeTruthy();
  });

  it('filters runner choices based on selected region', () => {
    const handleSubmit = vi.fn<[], Promise<void>>(() => Promise.resolve());

    render(
      <SessionComposer
        data={sampleData()}
        isLoading={false}
        error={null}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );

    const runnerSelect = screen.getByLabelText('Runner (опционально)');
    let options = within(runnerSelect).getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual([
      'Автовыбор (здоровые)',
      expect.stringContaining('runner-eu'),
    ]);

    const regionSelect = screen.getByLabelText('Регион');
    fireEvent.change(regionSelect, { target: { value: 'us' } });

    options = within(runnerSelect).getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual([
      'Автовыбор (здоровые)',
      expect.stringContaining('runner-us'),
    ]);
  });
});

afterEach(() => {
  cleanup();
});
