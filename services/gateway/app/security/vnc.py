"""Short-lived VNC token issuance utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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
            ttl_seconds: Lifetime of each token; must not exceed 300 seconds.
            issuer: Issuer claim embedded into generated tokens.

        Raises:
            ValueError: If ``ttl_seconds`` exceeds the contractually defined limit.
        """

        if ttl_seconds > 300:
            raise ValueError("VNC token TTL must be <= 300 seconds")
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
            ``token_ttl_seconds`` fields.
        """

        if details.token is not None:
            return details
        token, ttl = self.issue(session_id, subject=subject)
        return details.model_copy(update={"token": token, "token_ttl_seconds": ttl})
