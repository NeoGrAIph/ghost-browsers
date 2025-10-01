import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { openSessionEventStream } from '../api/client';
import { Session } from '../types/session';
import { queryKeys } from '../utils/queryKeys';

const MAX_RETRIES = 5;
const INITIAL_DELAY = 2_000;

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

/**
 * Subscribes to the session SSE stream and keeps the local cache in sync.
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
        const data = parseEvent(event);
        queryClient.setQueryData<{ sessions: Session[] }>(queryKeys.sessions, (current) => {
          if (!current) {
            return current;
          }

          if (data.type === 'deleted') {
            return {
              sessions: current.sessions.filter((session) => session.id !== data.sessionId),
            };
          }

          if (data.session) {
            return {
              sessions: mergeSession(current.sessions, data.session as Session),
            };
          }

          return current;
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
