import { create } from 'zustand';

export type SessionStatusFilter = 'all' | 'pending' | 'active' | 'failed' | 'completed';

interface SessionFiltersState {
  readonly search: string;
  readonly status: SessionStatusFilter;
  readonly region: string | null;
  readonly proxyId: string | null;
  readonly setSearch: (value: string) => void;
  readonly setStatus: (value: SessionStatusFilter) => void;
  readonly setRegion: (value: string | null) => void;
  readonly setProxyId: (value: string | null) => void;
  readonly reset: () => void;
}

const initialState = {
  search: '',
  status: 'all' as SessionStatusFilter,
  region: null,
  proxyId: null,
};

/**
 * Zustand store that keeps filtering criteria for the session list.
 */
export const useSessionFilters = create<SessionFiltersState>((set) => ({
  ...initialState,
  setSearch: (search) => set({ search }),
  setStatus: (status) => set({ status }),
  setRegion: (region) => set({ region }),
  setProxyId: (proxyId) => set({ proxyId }),
  reset: () => set(initialState),
}));
