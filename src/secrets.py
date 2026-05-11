"""
Secure credential management for GLMChat using OS-level keyring.

On Windows, credentials are stored in Windows Credential Manager.
On macOS, they go to Keychain. On Linux, to Secret Service (GNOME Keyring / KWallet).

Migration path:
  1. First run: reads from data/.env, migrates to keyring, removes from .env
  2. Subsequent runs: reads directly from keyring (never touches disk)
  3. Fallback: if keyring unavailable, falls back to .env with a warning
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_NAME = "GLMChat"
_EMAIL_KEY = "zai_email"
_PASSWORD_KEY = "zai_password"


def _keyring_available():
    """Check if keyring backend is usable."""
    try:
        import keyring
        # Some systems have keyring installed but no backend
        backend = keyring.get_keyring()
        # The fail backend means no real backend is available
        return "fail" not in type(backend).__name__.lower()
    except Exception:
        return False


def get_credentials():
    """
    Retrieve ZAI_EMAIL and ZAI_PASSWORD from the most secure source available.

    Priority: keyring → environment variables → .env file
    Returns (email, password) tuple. Either may be None.
    """
    if _keyring_available():
        import keyring
        email = keyring.get_password(_SERVICE_NAME, _EMAIL_KEY)
        password = keyring.get_password(_SERVICE_NAME, _PASSWORD_KEY)
        if email and password:
            return email, password
        logger.debug("Credentials not in keyring, checking env fallback")

    # Fallback to environment (already loaded by config.py via dotenv)
    email = os.getenv("ZAI_EMAIL")
    password = os.getenv("ZAI_PASSWORD")
    return email, password


def store_credentials(email, password):
    """
    Store credentials in OS keyring.
    Returns True if stored successfully, False if keyring unavailable.
    """
    if not _keyring_available():
        logger.warning("Keyring not available — credentials remain in .env")
        return False

    import keyring
    keyring.set_password(_SERVICE_NAME, _EMAIL_KEY, email)
    keyring.set_password(_SERVICE_NAME, _PASSWORD_KEY, password)
    return True


def migrate_from_env(env_path):
    """
    One-time migration: move credentials from .env to keyring.
    After successful migration, removes the sensitive lines from .env.

    Returns True if migration happened, False if skipped or failed.
    """
    env_file = Path(env_path)
    if not env_file.exists():
        return False

    email = os.getenv("ZAI_EMAIL")
    password = os.getenv("ZAI_PASSWORD")

    if not email or not password:
        return False

    if not store_credentials(email, password):
        return False

    # Remove sensitive lines from .env, keep other config
    lines = env_file.read_text(encoding="utf-8").splitlines()
    clean_lines = [
        line for line in lines
        if not line.strip().startswith("ZAI_EMAIL")
        and not line.strip().startswith("ZAI_PASSWORD")
    ]

    env_file.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")
    logger.info("Credentials migrated to OS keyring and removed from .env")
    return True


def store_token(token):
    """Store JWT token in keyring instead of plaintext file."""
    if not _keyring_available():
        return False
    import keyring
    keyring.set_password(_SERVICE_NAME, "jwt_token", token)
    return True


def get_token():
    """Retrieve JWT token from keyring."""
    if not _keyring_available():
        return None
    import keyring
    return keyring.get_password(_SERVICE_NAME, "jwt_token")
