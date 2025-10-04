/**
 * Minimal ghost mark used as the application logo.
 *
 * The icon is intentionally simple so it stays recognizable at small sizes
 * and matches the new friendly aesthetic requested for the operator console.
 * It exposes the same styling hook (`topbar__logo`) that the previous emoji
 * relied on so existing layout styles continue to apply.
 */
export function GhostLogo(): JSX.Element {
  return (
    <span className="topbar__logo" aria-hidden>
      <svg
        className="topbar__logo-asset"
        viewBox="0 0 64 64"
        role="presentation"
        focusable="false"
      >
        <path
          fill="currentColor"
          d="M32 6c-11.598 0-21 9.402-21 21v20.88c0 3.214 2.213 5.97 5.349 6.659 2.552.562 4.948-.52 6.651-2.167 1.663-1.607 4.342-1.607 6.005 0 1.703 1.647 4.098 2.73 6.65 2.167C47.788 53.85 50 51.094 50 47.88V27c0-11.598-9.402-21-21-21Zm-8.5 17.5a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0Zm17 0a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0Zm-8.5 12c3.645 0 6.94 1.905 8.828 4.764a1.5 1.5 0 0 1-2.518 1.65C36.916 39.386 34.58 38 32 38c-2.582 0-4.92 1.389-5.813 3.919a1.5 1.5 0 0 1-2.816-.981C24.26 37.377 27.84 35.5 32 35.5Z"
        />
      </svg>
    </span>
  );
}
