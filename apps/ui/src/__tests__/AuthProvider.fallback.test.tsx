import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

describe('AuthProvider without Keycloak configuration', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.stubEnv('VITE_KEYCLOAK_URL', '');
    vi.stubEnv('VITE_KEYCLOAK_REALM', '');
    vi.stubEnv('VITE_KEYCLOAK_CLIENT_ID', '');
  });

  afterEach(() => {
    vi.doUnmock('../pages/DashboardPage');
    vi.doUnmock('../pages/LoginPage');
    vi.doUnmock('../hooks/useSessionEvents');
    vi.resetModules();
    vi.unstubAllEnvs();
    cleanup();
  });

  it('renders the dashboard when authentication is not configured', async () => {
    const dashboardSpy = vi.fn(() => <div data-testid="dashboard" />);
    vi.doMock('../pages/DashboardPage', () => ({ DashboardPage: dashboardSpy }));
    vi.doMock('../pages/LoginPage', () => ({ LoginPage: () => <div data-testid="login" /> }));
    vi.doMock('../hooks/useSessionEvents', () => ({ useSessionEvents: vi.fn() }));

    const [{ AuthProvider }, { ThemeProvider }, { App }] = await Promise.all([
      import('../providers/AuthProvider'),
      import('../providers/ThemeProvider'),
      import('../App'),
    ]);

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <ThemeProvider>
            <App />
          </ThemeProvider>
        </AuthProvider>
      </QueryClientProvider>,
    );

    expect(screen.queryByTestId('dashboard')).not.toBeNull();
    expect(screen.queryByTestId('login')).toBeNull();
    expect(dashboardSpy).toHaveBeenCalledTimes(1);
    queryClient.clear();
  });
});
