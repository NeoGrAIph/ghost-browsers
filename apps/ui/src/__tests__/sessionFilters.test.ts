import { describe, beforeEach, expect, it } from 'vitest';
import { useSessionFilters } from '../store/sessionFilters';

const getState = () => useSessionFilters.getState();

describe('useSessionFilters', () => {
  beforeEach(() => {
    useSessionFilters.getState().reset();
  });

  it('updates search text', () => {
    const { setSearch } = getState();
    setSearch('abc');
    expect(getState().search).toBe('abc');
  });

  it('resets to initial values', () => {
    const { setStatus, setRegion, setProxyId, reset } = getState();
    setStatus('READY');
    setRegion('eu');
    setProxyId('proxy-1');
    reset();

    expect(getState()).toMatchObject({
      status: 'all',
      region: null,
      proxyId: null,
    });
  });
});
