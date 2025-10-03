"""Short-lived VNC token issuance utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from core import SessionVncDetails
from jose import jwt


class VncTokenService:
    """Issue JWT tokens that guard access to the VNC gateway."""

    def __init__(
        self,
        *,
        secret: str,
        ttl_seconds: int = 300,
        issuer: str = "camou-gateway",
    ) -> None:
        """Create a new token service.

        Args:
            secret: HMAC secret used to sign JWT tokens shared with the VNC
                gateway. The value must be identical to the
                ``Settings.token_secret`` configuration of the VNC gateway
                service.
            ttl_seconds: Lifetime of each token in seconds; must fall within the
                inclusive ``[1, 300]`` range.
            issuer: Issuer claim embedded into generated tokens.

        Raises:
            ValueError: If ``ttl_seconds`` falls outside the supported range or
                the secret is empty.
        """

        if ttl_seconds <= 0:
            raise ValueError("VNC token TTL must be between 1 and 300 seconds")
        if ttl_seconds > 300:
            raise ValueError("VNC token TTL must be between 1 and 300 seconds")
        if not secret:
            msg = "VNC token secret must be a non-empty string"
            raise ValueError(msg)
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._issuer = issuer

    def issue(self, session_id: str, *, subject: str | None = None) -> tuple[str, int]:
        """Generate a JWT for the given session identifier.

        Args:
            session_id: Identifier of the session protected by the token.
            subject: Optional subject propagated from the authenticated user.

        Returns:
            tuple[str, int]: The encoded JWT token and its TTL in seconds.

        Notes:
            The resulting JWT contains the following claims:

            ``sid``
                Session identifier the token is scoped to.
            ``exp``
                Expiration timestamp (UNIX epoch seconds) calculated from
                ``ttl_seconds``.
            ``iss``
                Issuer identifier (``camou-gateway`` by default).
            ``sub``
                Optional subject claim mirroring the authenticated user.
        """

        now = datetime.now(tz=UTC)
        expires = now + timedelta(seconds=self._ttl_seconds)
        payload: dict[str, Any] = {
            "sid": session_id,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "iss": self._issuer,
        }
        if subject is not None:
            payload["sub"] = subject
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return token, self._ttl_seconds

    def enrich_vnc_details(
        self,
        details: SessionVncDetails,
        *,
        session_id: str,
        subject: str | None = None,
    ) -> SessionVncDetails:
        """Attach a token to the provided VNC details when missing.

        Args:
            details: VNC descriptor supplied by the runner.
            session_id: Identifier of the associated session.
            subject: Optional authenticated subject for auditing.

        Returns:
            SessionVncDetails: Updated descriptor including ``token`` and
            ``token_ttl_seconds`` fields and query parameters that embed the
            token for iframe consumers.

        Notes:
            Runner services intentionally leave ``token`` and
            ``token_ttl_seconds`` empty so the gateway can append a signature.
            Whenever a token is absent this method will mint a fresh JWT using
            :meth:`issue` and inject it into the ``http_url`` and
            ``websocket_url`` query strings (when present) so callers can use
            the published URLs without setting extra headers.
        """

        if details.token is not None:
            return details
        token, ttl = self.issue(session_id, subject=subject)

        http_with_token = self._append_query_token(
            str(details.http_url) if details.http_url is not None else None,
            token,
        )
        ws_with_token = self._append_query_token(
            str(details.websocket_url) if details.websocket_url is not None else None,
            token,
        )

        payload: dict[str, Any] = {
            "token": token,
            "token_ttl_seconds": ttl,
        }
        if http_with_token is not None:
            payload["http_url"] = http_with_token
        if ws_with_token is not None:
            payload["websocket_url"] = ws_with_token
        return details.model_copy(update=payload)

    @staticmethod
    def _append_query_token(url: str | None, token: str) -> str | None:
        """Inject the freshly minted token into the provided URL query string.

        Args:
            url (str | None): Absolute VNC URL reported by the runner or
                overrides.
            token (str): Token issued by :meth:`issue`.

        Returns:
            str | None: Updated URL with the ``token`` query parameter when a
            URL was provided, otherwise ``None``.

        Example:
            >>> VncTokenService._append_query_token('https://vnc/view', 'abc')
            'https://vnc/view?token=abc'
        """

        if not url:
            return None
        parts = urlparse(url)
        query_items = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in {"token", "access_token"}
        ]
        query_items.append(("token", token))
        new_query = urlencode(query_items)
        return urlunparse(parts._replace(query=new_query))
