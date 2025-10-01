import { useMemo } from 'react';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { useAuth } from './hooks/useAuth';
import { useSessionEvents } from './hooks/useSessionEvents';
import { useAppTheme } from './providers/ThemeProvider';

/**
 * Root application component that decides whether to render the dashboard or the login screen
 * based on the current authentication state.
 */
export function App(): JSX.Element {
  const { isAuthenticated, isLoading, token } = useAuth();
  const { theme } = useAppTheme();

  useSessionEvents({ enabled: isAuthenticated, token: token ?? undefined });

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
