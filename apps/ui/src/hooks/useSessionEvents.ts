import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { openSessionEventStream } from '../api/client';
import type { Session, SessionEvent } from '../types/session';
import { queryKeys } from '../utils/queryKeys';

const MAX_RETRIES = 5;
const INITIAL_DELAY = 2_000;

/**
 * Configuration object accepted by {@link useSessionEvents}.
 *
 * @property enabled - Toggles subscription side effects. When ``false`` the hook disconnects.
 * @property token - Optional bearer token forwarded to the SSE endpoint.
 */
export interface UseSessionEventsOptions {
  readonly enabled: boolean;
  readonly token?: string;
}

const mergeSession = (sessions: Session[], incoming: Session): Session[] => {
  const index = sessions.findIndex((session) => session.id === incoming.id);
  if (index === -1) {
    return [incoming, ...sessions];
  }

  const next = [...sessions];
  next[index] = { ...next[index], ...incoming };
  return next;
};

const removeSession = (sessions: Session[], sessionId: string): Session[] =>
  sessions.filter((session) => session.id !== sessionId);

/**
 * Subscribes to the session SSE stream and keeps the local cache in sync.
 *
 * @param options - Hook options controlling connectivity and authentication.
 * @example
 * ```tsx
 * useSessionEvents({ enabled: isAuthenticated, token: keycloakToken });
 * ```
 */
export const useSessionEvents = ({ enabled, token }: UseSessionEventsOptions) => {
  const queryClient = useQueryClient();
  const retryCount = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      retryCount.current = 0;
      return;
    }

    const connect = () => {
      const { eventSource, parseEvent } = openSessionEventStream({ token });
      eventSourceRef.current = eventSource;

      eventSource.onmessage = (event: MessageEvent<string>) => {
        const data = parseEvent(event) as SessionEvent;
        queryClient.setQueryData<Session[]>(queryKeys.sessions, (current) => {
          if (!current) {
            return current;
          }

          if (!data.session) {
            return current;
          }

          const sessionId = data.session.id;
          switch (data.type) {
            case 'session.ended':
              return removeSession(current, sessionId);
            case 'session.created':
            case 'session.updated':
              return mergeSession(current, data.session);
            default:
              return current;
          }
        });
      };

      eventSource.onerror = () => {
        eventSource.close();
        retryCount.current += 1;
        if (retryCount.current > MAX_RETRIES) {
          return;
        }

        const delay = INITIAL_DELAY * 2 ** (retryCount.current - 1);
        window.setTimeout(() => {
          connect();
        }, delay);
      };

      eventSource.onopen = () => {
        retryCount.current = 0;
      };
    };

    connect();

    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, [enabled, queryClient, token]);
};
