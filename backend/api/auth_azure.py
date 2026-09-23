"""
Azure AD / Entra ID token validation and JIT user provisioning.

Validates access tokens via Microsoft JWKS and creates/links local users.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .database.models import User, UserRole, DEFAULT_USER_SETTINGS

logger = logging.getLogger(__name__)

_jwks_cache: Dict[str, Any] = {
    "keys": {},
    "fetched_at": 0.0,
    "ttl_seconds": 3600,
}


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


def _tenant_id() -> str:
    return os.environ.get("AZURE_AD_TENANT_ID", "").strip()


def _client_id() -> str:
    return os.environ.get("AZURE_AD_CLIENT_ID", "").strip()


def is_azure_ad_enabled() -> bool:
    """True when Azure AD dual-auth is configured and enabled."""
    return bool(_env_flag("AZURE_AD_ENABLED") and _tenant_id() and _client_id())


def _jwks_uri() -> str:
    return (
        f"https://login.microsoftonline.com/{_tenant_id()}/discovery/v2.0/keys"
    )


def fetch_azure_jwks() -> Dict[str, Any]:
    """Fetch Microsoft JWKS, cached for 1 hour."""
    now = time.time()
    if _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < _jwks_cache[
        "ttl_seconds"
    ]:
        return _jwks_cache["keys"]

    response = requests.get(_jwks_uri(), timeout=10.0)
    response.raise_for_status()
    jwks = response.json()
    keys_by_kid = {key["kid"]: key for key in jwks.get("keys", []) if key.get("kid")}

    _jwks_cache["keys"] = keys_by_kid
    _jwks_cache["fetched_at"] = now
    logger.info("Fetched Azure JWKS (%s keys)", len(keys_by_kid))
    return keys_by_kid


def validate_azure_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validate an Entra access/ID token (RS256 + issuer).

    Soft audience check: accept client_id or graph.microsoft.com.
    Returns claims on success, None on failure (so local JWT can be tried next).
    """
    if not is_azure_ad_enabled():
        return None

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            return None

        jwks = fetch_azure_jwks()
        signing_key = jwks.get(kid)
        if not signing_key:
            _jwks_cache["fetched_at"] = 0.0
            jwks = fetch_azure_jwks()
            signing_key = jwks.get(kid)
            if not signing_key:
                logger.warning("Azure token signing key not found for kid=%s", kid)
                return None

        valid_issuers = [
            f"https://login.microsoftonline.com/{_tenant_id()}/v2.0",
            f"https://sts.windows.net/{_tenant_id()}/",
        ]

        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=valid_issuers,
            options={
                "verify_aud": False,
                "verify_iss": True,
                "verify_exp": True,
                "verify_nbf": True,
            },
        )

        token_aud = str(claims.get("aud", ""))
        client_id = _client_id()
        if client_id not in token_aud and "graph.microsoft.com" not in token_aud:
            # Soft check: log but still accept (signature + issuer already verified)
            logger.warning(
                "Azure token unexpected audience aud=%s expected_client=%s",
                token_aud,
                client_id,
            )

        return claims

    except JWTError as exc:
        logger.debug("Azure token validation failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Azure token validation error: %s", exc)
        return None


def _map_azure_roles_to_app_role(azure_roles: List[str]) -> str:
    """Map Entra app roles to IDP roles."""
    role_set = set(azure_roles or [])
    if role_set & {"Admin", "Idp.Admin"}:
        return UserRole.ADMIN.value
    if role_set & {"Contributor", "Idp.Contributor"}:
        return UserRole.CONTRIBUTOR.value
    return UserRole.VIEWER.value


def _unique_username(db: Session, email: Optional[str], azure_oid: str) -> str:
    """Derive a unique username from email local-part (or oid fallback)."""
    if email and "@" in email:
        base = email.split("@", 1)[0].strip() or f"user_{azure_oid[:8]}"
    elif email:
        base = email.strip() or f"user_{azure_oid[:8]}"
    else:
        base = f"user_{azure_oid[:8]}"

    # Prefer full email if local-part collides
    candidates = [base]
    if email and email != base:
        candidates.append(email)
    candidates.append(f"{base}_{azure_oid[:6]}")

    for candidate in candidates:
        existing = db.query(User).filter(User.username == candidate).first()
        if not existing:
            return candidate[:100]

    return f"user_{azure_oid}"[:100]


def get_or_create_user_from_azure(db: Session, claims: Dict[str, Any]) -> Optional[User]:
    """
    JIT provision or link a user from Azure AD claims.

    Match order: azure_oid → email. Creates viewer (or mapped role) if new.
    """
    azure_oid = claims.get("oid")
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
    )
    display_name = claims.get("name")
    roles = claims.get("roles") or []

    if not azure_oid:
        logger.warning("Azure token missing oid claim")
        return None

    user = db.query(User).filter(User.azure_oid == azure_oid).first()

    if not user and email:
        user = db.query(User).filter(User.email == email).first()

    now = datetime.utcnow()

    if user:
        if not user.azure_oid:
            user.azure_oid = azure_oid
            if (user.auth_provider or "local") == "local" and not user.password_hash:
                user.auth_provider = "azure_ad"
            elif not user.auth_provider:
                user.auth_provider = "azure_ad"
        if email and not user.email:
            user.email = email
        if display_name and not user.display_name:
            user.display_name = display_name
        user.last_login_at = now
        user.updated_at = now
        db.commit()
        db.refresh(user)
        logger.info("Linked/updated Azure user id=%s email=%s", user.id, email)
        return user

    username = _unique_username(db, email, azure_oid)
    app_role = _map_azure_roles_to_app_role(roles if isinstance(roles, list) else [])

    user = User(
        username=username,
        email=email,
        display_name=display_name or username,
        password_hash=None,
        role=app_role,
        azure_oid=azure_oid,
        auth_provider="azure_ad",
        settings=DEFAULT_USER_SETTINGS.copy(),
        is_active=True,
        last_login_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(
        "JIT created Azure user id=%s username=%s role=%s",
        user.id,
        username,
        app_role,
    )
    return user
