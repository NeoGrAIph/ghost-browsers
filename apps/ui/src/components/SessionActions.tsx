import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { deleteSession, updateSessionProxy } from '../api/client';
import { queryKeys } from '../utils/queryKeys';
import { Session, SessionProxyUpdateSchema, type SessionProxyUpdate } from '../types/session';
import { useAuth } from '../hooks/useAuth';

interface SessionActionsProps {
  readonly session: Session | null;
}

/**
 * Action buttons for the selected session.
 */
export function SessionActions({ session }: SessionActionsProps): JSX.Element {
  const queryClient = useQueryClient();
  const { token } = useAuth();
  const [httpProxy, setHttpProxy] = useState('');
  const [httpsProxy, setHttpsProxy] = useState('');
  const [socksProxy, setSocksProxy] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await deleteSession(sessionId, { token: token ?? undefined });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });

  const {
    mutate: submitProxy,
    reset: resetProxy,
    isPending: isUpdatingProxy,
    isSuccess: isProxyUpdated,
  } = useMutation({
    mutationFn: async ({ sessionId, payload }: { sessionId: string; payload: SessionProxyUpdate }) =>
      updateSessionProxy(sessionId, payload, { token: token ?? undefined }),
    onSuccess: (updatedSession) => {
      setFormError(null);
      queryClient.setQueryData<Session[] | undefined>(queryKeys.sessions, (current) => {
        if (!current) {
          return current;
        }
        return current.map((existing) => (existing.id === updatedSession.id ? updatedSession : existing));
      });
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Не удалось обновить прокси.';
      setFormError(message);
    },
  });

  useEffect(() => {
    setHttpProxy(session?.proxy?.http ?? '');
    setHttpsProxy(session?.proxy?.https ?? '');
    setSocksProxy(session?.proxy?.socks ?? '');
    setFormError(null);
    resetProxy();
  }, [session, resetProxy]);

  const sanitizeValue = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!session) {
      return;
    }

    const candidate = {
      http: sanitizeValue(httpProxy),
      https: sanitizeValue(httpsProxy),
      socks: sanitizeValue(socksProxy),
    } satisfies SessionProxyUpdate;

    const parsed = SessionProxyUpdateSchema.safeParse(candidate);
    if (!parsed.success) {
      setFormError('Укажите корректные URL и заполните хотя бы одно поле.');
      return;
    }

    setFormError(null);
    submitProxy({ sessionId: session.id, payload: parsed.data });
  };

  const isFormDisabled = !session || isUpdatingProxy;

  return (
    <div className="session-actions">
      <form onSubmit={handleSubmit} className="session-actions__form">
        <fieldset disabled={isFormDisabled}>
          <legend>Прокси</legend>
          <label className="session-actions__field">
            HTTP прокси
            <input
              type="url"
              value={httpProxy}
              onChange={(event) => setHttpProxy(event.target.value)}
              placeholder="http://proxy.local:3128"
            />
          </label>
          <label className="session-actions__field">
            HTTPS прокси
            <input
              type="url"
              value={httpsProxy}
              onChange={(event) => setHttpsProxy(event.target.value)}
              placeholder="https://proxy.local:3129"
            />
          </label>
          <label className="session-actions__field">
            SOCKS прокси
            <input
              type="url"
              value={socksProxy}
              onChange={(event) => setSocksProxy(event.target.value)}
              placeholder="socks5://proxy.local:1080"
            />
          </label>
          <div className="session-actions__controls">
            <button type="submit">Сохранить</button>
            {isProxyUpdated && !formError && <span role="status">Сохранено</span>}
          </div>
          {formError && (
            <p role="alert" className="session-actions__error">
              {formError}
            </p>
          )}
        </fieldset>
      </form>
      <button
        type="button"
        className="danger"
        onClick={() => {
          if (!session) {
            return;
          }
          deleteMutation.mutate(session.id);
        }}
        disabled={!session || deleteMutation.isPending}
      >
        Удалить
      </button>
    </div>
  );
}
