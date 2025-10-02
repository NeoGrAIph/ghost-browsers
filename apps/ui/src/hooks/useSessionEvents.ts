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
  readonly retrySignal?: number;
  readonly onError?: (error: Error | null) => void;
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
 *
 * @param enabled - Controls whether the SSE connection should be active.
 * @param token - Optional bearer token that will be forwarded as `access_token` query.
 * @param retrySignal - External signal that forces the hook to re-connect to the stream.
 * @param onError - Callback invoked with the terminal connection error or `null` when recovered.
 */
export const useSessionEvents = ({
  enabled,
  token,
  retrySignal = 0,
  onError,
}: UseSessionEventsOptions) => {
  const queryClient = useQueryClient();
  const retryCount = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      retryCount.current = 0;
      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      onError?.(null);
      return;
    }

    const connect = () => {
      const { eventSource, parseEvent } = openSessionEventStream({ token });
      eventSourceRef.current = eventSource;

      eventSource.onmessage = (event: MessageEvent<string>) => {
        const data = parseEvent(event);
        queryClient.setQueryData<Session[]>(queryKeys.sessions, (current) => {
          const baseline = current ?? [];
          return mergeSession(baseline, data.session);
        });
      };

      eventSource.onerror = () => {
        eventSource.close();
        retryCount.current += 1;
        if (retryCount.current > MAX_RETRIES) {
          onError?.(
            new Error(
              `Не удалось подключиться к потоку событий после ${MAX_RETRIES} попыток.`,
            ),
          );
          return;
        }

        const delay = INITIAL_DELAY * 2 ** (retryCount.current - 1);
        if (reconnectTimeoutRef.current !== null) {
          window.clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, delay);
      };

      eventSource.onopen = () => {
        retryCount.current = 0;
        onError?.(null);
      };
    };

    retryCount.current = 0;
    onError?.(null);
    connect();

    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [enabled, onError, queryClient, retrySignal, token]);
};
