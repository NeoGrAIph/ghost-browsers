import { useAuth } from '../hooks/useAuth';
import { useAppTheme } from '../providers/ThemeProvider';

/**
 * Application top bar with user info and theme toggle.
 */
export function Topbar(): JSX.Element {
  const { profile, logout } = useAuth();
  const { theme, toggleTheme } = useAppTheme();

  return (
    <header className="topbar" role="banner">
      <div className="topbar__brand">
        <span className="topbar__logo" aria-hidden>🕵🏻‍♂️</span>
        <div>
          <strong>Ghost Browsers</strong>
          <span className="topbar__subtitle">Операторская консоль</span>
        </div>
      </div>
      <div className="topbar__actions">
        <button type="button" className="ghost" onClick={toggleTheme}>
          Тема: {theme === 'dark' ? '🌙' : '☀️'}
        </button>
        <div className="topbar__profile" role="group" aria-label="Профиль оператора">
          <span className="topbar__profile-name">{profile?.firstName ?? 'Оператор'}</span>
          <button type="button" className="ghost" onClick={() => void logout()}>
            Выйти
          </button>
        </div>
      </div>
    </header>
  );
}
