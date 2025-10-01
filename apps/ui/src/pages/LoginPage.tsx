import { useAuth } from '../hooks/useAuth';

/**
 * Login screen rendered when the user is unauthenticated.
 */
export function LoginPage(): JSX.Element {
  const { login, isLoading } = useAuth();

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <h1>Ghost Browsers Console</h1>
        <p>Для продолжения войдите через корпоративный Keycloak.</p>
        <button type="button" className="primary" onClick={() => void login()} disabled={isLoading}>
          Войти
        </button>
      </div>
    </div>
  );
}
