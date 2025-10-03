import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import Keycloak, { KeycloakError, KeycloakProfile, KeycloakTokenParsed } from 'keycloak-js';

interface AuthState {
  readonly isLoading: boolean;
  readonly isAuthenticated: boolean;
  readonly token: string | null;
  readonly parsedToken: KeycloakTokenParsed | undefined;
  readonly profile: KeycloakProfile | null;
  readonly keycloak: Keycloak | null;
}

interface AuthContextValue extends AuthState {
  readonly login: () => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly refreshToken: () => Promise<void>;
}

const keycloakUrl = import.meta.env.VITE_KEYCLOAK_URL;
const keycloakRealm = import.meta.env.VITE_KEYCLOAK_REALM;
const keycloakClientId = import.meta.env.VITE_KEYCLOAK_CLIENT_ID;

const isAuthConfigured = Boolean(keycloakUrl && keycloakRealm && keycloakClientId);

/**
 * React context exposing the authentication state maintained by {@link AuthProvider}.
 *
 * @remarks
 * Consumers can rely on `keycloak` being `null` whenever Keycloak integration is disabled.
 *
 * @example
 * const { profile } = useAuth();
 */
export const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  readonly children: ReactNode;
}

const createLocalProfile = (): KeycloakProfile => ({
  firstName: 'Оператор',
  username: 'local-operator',
});

const buildLocalAuthState = (): AuthState => ({
  isAuthenticated: true,
  isLoading: false,
  keycloak: null,
  parsedToken: undefined,
  profile: createLocalProfile(),
  token: null,
});

const buildRemoteAuthState = (): AuthState => ({
  isAuthenticated: false,
  isLoading: true,
  keycloak: null,
  parsedToken: undefined,
  profile: null,
  token: null,
});

/**
 * Provides authentication state to the component tree and manages Keycloak session refreshes.
 *
 * @param props.children React subtree that consumes the authentication context.
 * @returns Provider element wiring the current authentication state to descendants.
 *
 * @throws never
 *
 * @remarks
 * When Keycloak environment variables are absent the provider synthesizes a local operator
 * session (token and Keycloak client are `null`) so the UI remains usable during development.
 * Otherwise, it initialises a Keycloak client, keeps tokens refreshed in the background, and
 * exposes the received profile to consumers.
 *
 * @example
 * <AuthProvider>
 *   <App />
 * </AuthProvider>
 */
export function AuthProvider({ children }: AuthProviderProps): JSX.Element {
  const keycloakRef = useRef<Keycloak>();
  const [state, setState] = useState<AuthState>(() =>
    isAuthConfigured ? buildRemoteAuthState() : buildLocalAuthState(),
  );

  useEffect(() => {
    if (!isAuthConfigured) {
      // Preserve the synthetic authenticated session whenever Keycloak env variables are missing.
      setState(buildLocalAuthState());
      return;
    }

    const keycloak = new Keycloak({
      url: keycloakUrl,
      realm: keycloakRealm,
      clientId: keycloakClientId,
    });

    keycloakRef.current = keycloak;
    let mounted = true;

    void keycloak
      .init({
        onLoad: 'check-sso',
        silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
        pkceMethod: 'S256',
        checkLoginIframe: false,
      })
      .then(async (authenticated) => {
        if (!mounted) {
          return;
        }

        if (authenticated) {
          const profile = await keycloak.loadUserProfile();
          setState({
            isAuthenticated: true,
            isLoading: false,
            keycloak,
            parsedToken: keycloak.tokenParsed,
            profile,
            token: keycloak.token ?? null,
          });
        } else {
          setState({
            isAuthenticated: false,
            isLoading: false,
            keycloak,
            parsedToken: keycloak.tokenParsed,
            profile: null,
            token: null,
          });
        }
      })
      .catch((error: KeycloakError) => {
        console.error('Keycloak init error', error);
        if (!mounted) {
          return;
        }

        setState({
          isAuthenticated: false,
          isLoading: false,
          keycloak,
          parsedToken: undefined,
          profile: null,
          token: null,
        });
      });

    const handleToken = async () => {
      if (!keycloak.token) {
        return;
      }

      try {
        await keycloak.updateToken(30);
        setState((current) => ({
          ...current,
          token: keycloak.token ?? null,
          parsedToken: keycloak.tokenParsed,
        }));
      } catch (error) {
        console.error('Failed to refresh Keycloak token', error);
      }
    };

    keycloak.onTokenExpired = () => {
      void handleToken();
    };

    const intervalId = window.setInterval(() => {
      void handleToken();
    }, 20_000);

    return () => {
      mounted = false;
      window.clearInterval(intervalId);
      keycloak.onTokenExpired = undefined;
    };
  }, []);

  const login = useCallback(async () => {
    if (!isAuthConfigured || !keycloakRef.current) {
      return;
    }

    await keycloakRef.current.login({ prompt: 'login' });
  }, []);

  const logout = useCallback(async () => {
    if (!keycloakRef.current) {
      return;
    }

    await keycloakRef.current.logout({ redirectUri: window.location.origin });
  }, []);

  const refreshToken = useCallback(async () => {
    if (!keycloakRef.current) {
      return;
    }

    await keycloakRef.current.updateToken(30);
    setState((current) => ({
      ...current,
      token: keycloakRef.current?.token ?? null,
      parsedToken: keycloakRef.current?.tokenParsed,
    }));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      login,
      logout,
      refreshToken,
    }),
    [login, logout, refreshToken, state],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
