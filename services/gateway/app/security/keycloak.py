"""Keycloak JWT validation utilities."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

import httpx
from jose import jwk, jwt
from jose.exceptions import JOSEError
from jose.utils import base64url_decode

_LOGGER = logging.getLogger("gateway.security")


@dataclass(slots=True)
class AuthenticatedUser:
    """Represents the authenticated principal extracted from a JWT."""

    subject: str
    email: str | None = None


class AuthenticationError(RuntimeError):
    """Raised when the supplied JWT cannot be verified."""


class KeycloakAuthenticator:
    """Validate Keycloak-issued JWTs using JWKS metadata."""

    def __init__(self, jwks_url: str, *, audience: str | None = None) -> None:
        """Initialise the authenticator with JWKS location and optional audience."""

        self._jwks_url = jwks_url
        self._audience = audience
        self._jwks_cache: dict[str, Mapping[str, Any]] | None = None
        self._jwks_lock = asyncio.Lock()

    async def authenticate(self, token: str) -> AuthenticatedUser:
        """Verify the token signature and extract the principal information.

        Args:
            token: Bearer token supplied by the caller.

        Returns:
            AuthenticatedUser: Subject and email extracted from the claims set.

        Raises:
            AuthenticationError: If the token header or claims are invalid or the
                signature check fails.
        """

        try:
            header = jwt.get_unverified_header(token)
        except JOSEError as exc:  # pragma: no cover - jose already tested
            raise AuthenticationError("Invalid token header") from exc
        kid = header.get("kid")
        if not kid:
            raise AuthenticationError("JWT header missing 'kid'")
        key_dict = await self._get_key(kid)
        message, encoded_signature = token.rsplit(".", 1)
        signature = base64url_decode(encoded_signature.encode("utf-8"))
        try:
            constructed_key = jwk.construct(key_dict)
        except JOSEError as exc:  # pragma: no cover - defensive branch
            raise AuthenticationError("Unable to construct verification key") from exc
        if not constructed_key.verify(message.encode("utf-8"), signature):
            raise AuthenticationError("Token signature verification failed")
        claims = jwt.get_unverified_claims(token)
        self._validate_claims(claims)
        subject = str(claims.get("sub"))
        if not subject:
            raise AuthenticationError("JWT is missing subject claim")
        email = claims.get("email") or claims.get("preferred_username")
        _LOGGER.info("authenticated", extra={"sub": subject, "email": email})
        return AuthenticatedUser(subject=subject, email=email)

    async def _get_key(self, kid: str) -> Mapping[str, Any]:
        """Return the JWKS entry for the given key identifier."""

        async with self._jwks_lock:
            if self._jwks_cache is None:
                self._jwks_cache = await self._fetch_jwks()
            key = self._jwks_cache.get(kid)
            if key is None:
                # Refresh JWKS in case Keycloak rotated the key set.
                self._jwks_cache = await self._fetch_jwks()
                key = self._jwks_cache.get(kid)
            if key is None:
                raise AuthenticationError("Signing key not found in JWKS")
            return key

    async def _fetch_jwks(self) -> dict[str, Mapping[str, Any]]:
        """Download JWKS metadata and index it by ``kid``."""

        async with httpx.AsyncClient() as client:
            response = await client.get(self._jwks_url, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        keys = data.get("keys", [])
        if not isinstance(keys, list):
            raise AuthenticationError("JWKS payload is malformed")
        indexed: dict[str, Mapping[str, Any]] = {}
        for item in keys:
            if not isinstance(item, Mapping) or "kid" not in item:
                raise AuthenticationError("Invalid key entry in JWKS")
            indexed[str(item["kid"])] = item
        if not indexed:
            raise AuthenticationError("JWKS document does not contain keys")
        return indexed

    def _validate_claims(self, claims: Mapping[str, Any]) -> None:
        """Validate expiry and optional audience claims."""

        expires_at = claims.get("exp")
        if expires_at is not None:
            expiry = datetime.fromtimestamp(int(expires_at), tz=UTC)
            if expiry <= datetime.now(tz=UTC):
                raise AuthenticationError("Token has expired")
        if self._audience is None:
            return
        audience = claims.get("aud")
        if isinstance(audience, str):
            audiences = {audience}
        elif isinstance(audience, list):
            audiences = {str(item) for item in audience}
        else:
            audiences = set()
        if self._audience not in audiences:
            raise AuthenticationError("Token audience mismatch")
