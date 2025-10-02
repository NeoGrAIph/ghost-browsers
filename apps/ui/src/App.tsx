import { useCallback, useEffect, useMemo } from 'react';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { useAuth } from './hooks/useAuth';
import { useSessionEvents } from './hooks/useSessionEvents';
import { useAppTheme } from './providers/ThemeProvider';
import { useSessionEventConnection } from './store/sessionEvents';

/**
 * Root application component that decides whether to render the dashboard or the login screen
 * based on the current authentication state.
 */
export function App(): JSX.Element {
  const { isAuthenticated, isLoading, token } = useAuth();
  const { theme } = useAppTheme();
  const retrySignal = useSessionEventConnection((state) => state.retrySignal);
  const setConnectionError = useSessionEventConnection((state) => state.setError);
  const resetConnectionState = useSessionEventConnection((state) => state.reset);

  useEffect(() => {
    if (!isAuthenticated) {
      resetConnectionState();
    }
  }, [isAuthenticated, resetConnectionState]);

  const handleStreamError = useCallback(
    (error: Error | null) => {
      setConnectionError(error ? error.message : null);
    },
    [setConnectionError],
  );

  useSessionEvents({
    enabled: isAuthenticated,
    token: token ?? undefined,
    retrySignal,
    onError: handleStreamError,
  });

  const content = useMemo(() => {
    if (isLoading) {
      return (
        <div className="app-loading" role="status" aria-live="polite">
          <div className="spinner" />
          <p>Загружаем консоль…</p>
        </div>
      );
    }

    if (!isAuthenticated) {
      return <LoginPage />;
    }

    return <DashboardPage />;
  }, [isAuthenticated, isLoading]);

  return <div className={`app app--${theme}`}>{content}</div>;
}
