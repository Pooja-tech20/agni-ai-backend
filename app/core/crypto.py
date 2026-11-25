"""Symmetric encryption for third-party credentials stored in the database."""
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretsNotConfigured(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = settings.SECRETS_ENCRYPTION_KEY
    if not key:
        raise SecretsNotConfigured(
            "SECRETS_ENCRYPTION_KEY is not set; cannot store integration credentials."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # wrong key or corrupted value
        raise SecretsNotConfigured("Stored credential cannot be decrypted with the current key.") from exc
