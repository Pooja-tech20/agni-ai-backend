# from datetime import datetime, timedelta, timezone

# from jose import JWTError, jwt
# from pwdlib import PasswordHash

# from app.core.config import settings

# password_hash = PasswordHash.recommended()


# def hash_password(password: str) -> str:
#     """Hash a plain-text password."""
#     return password_hash.hash(password)


# def verify_password(
#     plain_password: str,
#     hashed_password: str,
# ) -> bool:
#     """Verify a plain-text password against its hash."""
#     return password_hash.verify(
#         plain_password,
#         hashed_password,
#     )


# def _create_token(user_id: str, role: str, lifetime: timedelta, token_type: str) -> str:
#     payload = {
#         "sub": user_id,
#         "role": role,
#         "type": token_type,
#         "exp": datetime.now(timezone.utc) + lifetime,
#     }
#     return jwt.encode(
#         payload,
#         settings.JWT_SECRET_KEY,
#         algorithm=settings.JWT_ALGORITHM,
#     )


# def create_access_token(user_id: str, role: str) -> str:
#     """Short-lived JWT sent with every API request."""
#     return _create_token(
#         user_id, role, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access"
#     )


# def create_refresh_token(user_id: str, role: str) -> str:
#     """Long-lived JWT used only to get a new access token (POST /auth/refresh)."""
#     return _create_token(
#         user_id, role, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh"
#     )


# def _decode(token: str) -> dict:
#     return jwt.decode(
#         token,
#         settings.JWT_SECRET_KEY,
#         algorithms=[settings.JWT_ALGORITHM],
#     )


# def decode_access_token(token: str) -> dict:
#     """Decode and validate an access token (refresh tokens are rejected)."""
#     try:
#         payload = _decode(token)
#     except JWTError:
#         raise ValueError("Invalid or expired access token")
#     # Tokens issued before refresh tokens existed have no "type" and still work
#     if payload.get("type") == "refresh":
#         raise ValueError("Invalid or expired access token")
#     return payload


# def decode_refresh_token(token: str) -> dict:
#     """Decode and validate a refresh token (access tokens are rejected)."""
#     try:
#         payload = _decode(token)
#     except JWTError:
#         raise ValueError("Invalid or expired refresh token")
#     if payload.get("type") != "refresh":
#         raise ValueError("Invalid or expired refresh token")
#     return payload


import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from pwdlib import PasswordHash

from app.core.config import settings

logger = logging.getLogger(__name__)

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plain-text password."""
    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Verify a plain-text password against its hash."""
    return password_hash.verify(
        plain_password,
        hashed_password,
    )


def _create_token(user_id: str, role: str, lifetime: timedelta, token_type: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + lifetime,
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(user_id: str, role: str) -> str:
    """Short-lived JWT sent with every API request."""
    return _create_token(
        user_id, role, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access"
    )


def create_refresh_token(user_id: str, role: str) -> str:
    """Long-lived JWT used only to get a new access token (POST /auth/refresh)."""
    return _create_token(
        user_id, role, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh"
    )


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token (refresh tokens are rejected)."""
    try:
        payload = _decode(token)
    except JWTError as exc:
        # Log WHY (expired / bad signature / malformed) - never the token itself.
        logger.warning(
            "Access token rejected: %s (token length=%d)", exc, len(token or "")
        )
        raise ValueError("Invalid or expired access token")
    # Tokens issued before refresh tokens existed have no "type" and still work
    if payload.get("type") == "refresh":
        logger.warning("Access token rejected: a refresh token was sent")
        raise ValueError("Invalid or expired access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token (access tokens are rejected)."""
    try:
        payload = _decode(token)
    except JWTError:
        raise ValueError("Invalid or expired refresh token")
    if payload.get("type") != "refresh":
        raise ValueError("Invalid or expired refresh token")
    return payload 
