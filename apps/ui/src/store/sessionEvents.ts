import { create } from 'zustand';

interface SessionEventConnectionState {
  readonly error: string | null;
  readonly retrySignal: number;
  readonly setError: (value: string | null) => void;
  readonly requestRetry: () => void;
  readonly reset: () => void;
}

const initialState = {
  error: null as string | null,
  retrySignal: 0,
};

/**
 * Zustand store that tracks the SSE connection status for session events.
 */
export const useSessionEventConnection = create<SessionEventConnectionState>((set) => ({
  ...initialState,
  setError: (error) => set({ error }),
  requestRetry: () =>
    set((state) => ({
      error: null,
      retrySignal: state.retrySignal + 1,
    })),
  reset: () => set(initialState),
}));
