"""Passphrase-encrypted vault for the Facebook login and session.

Everything secret (email, password, browser session cookies) lives in one
file, VAULT_FILE, encrypted with a key derived from a passphrase you choose.
Nothing depends on an OS keychain, so it behaves the same on Windows, macOS,
Linux and in Docker.

File layout: 16-byte random salt + Fernet token (AES-128-CBC + HMAC-SHA256).
The key is derived from the passphrase with scrypt, which makes guessing the
passphrase slow even if someone gets the file.

The passphrase comes from the SCRAPER_PASSPHRASE environment variable if set
(for servers / Docker), otherwise it's asked for interactively.
"""
import base64
import json
import os
import sys
from datetime import datetime
from getpass import getpass

from cryptography.exceptions import InvalidKey
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from config import VAULT_FILE

PASSPHRASE_ENV = "SCRAPER_PASSPHRASE"
_SALT_LEN = 16
_passphrase = None  # cached for the life of the process


class VaultError(Exception):
    pass


def _derive_key(passphrase, salt):
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def vault_exists():
    return os.path.isfile(VAULT_FILE)


def get_passphrase(confirm=False):
    """Passphrase from env, cache, or prompt. confirm=True asks twice (new vault)."""
    global _passphrase
    if _passphrase:
        return _passphrase
    passphrase = os.getenv(PASSPHRASE_ENV)
    if not passphrase:
        if not sys.stdin.isatty():
            raise VaultError(f"No passphrase: set {PASSPHRASE_ENV} or run in a terminal.")
        passphrase = getpass("Vault passphrase (hidden): ")
        if confirm and getpass("Repeat passphrase: ") != passphrase:
            raise VaultError("Passphrases don't match.")
    if len(passphrase) < 8:
        raise VaultError("Passphrase must be at least 8 characters.")
    _passphrase = passphrase
    return passphrase


def set_passphrase(passphrase):
    """Use this passphrase from now on (the dashboard asks for it in the page).

    For an existing vault it must open it; for a new one it's what the vault
    will be created with on the first save.
    """
    global _passphrase
    if len(passphrase or "") < 8:
        raise VaultError("Passphrase must be at least 8 characters.")
    if vault_exists():
        _read(passphrase)  # raises if wrong
    _passphrase = passphrase


def is_unlocked():
    return bool(_passphrase or os.getenv(PASSPHRASE_ENV))


def _read(passphrase):
    with open(VAULT_FILE, "rb") as f:
        blob = f.read()
    salt, token = blob[:_SALT_LEN], blob[_SALT_LEN:]
    try:
        return json.loads(Fernet(_derive_key(passphrase, salt)).decrypt(token))
    except (InvalidToken, InvalidKey, ValueError):
        raise VaultError("Wrong passphrase, or the vault file is damaged.") from None


def _write(data, passphrase):
    salt = os.urandom(_SALT_LEN)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(json.dumps(data).encode("utf-8"))
    tmp = VAULT_FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(salt + token)
    os.replace(tmp, VAULT_FILE)
    try:
        os.chmod(VAULT_FILE, 0o600)  # owner-only on macOS/Linux; no-op on Windows
    except OSError:
        pass


def load_vault():
    if not vault_exists():
        return {}
    return _read(get_passphrase())


def update_vault(**fields):
    """Merge fields into the vault, creating it (and asking for a new passphrase) if needed."""
    data = load_vault() if vault_exists() else {}
    passphrase = get_passphrase(confirm=not vault_exists())
    data.update(fields)
    _write(data, passphrase)


def unlock():
    """Check the passphrase now (raises VaultError if wrong)."""
    load_vault()


def get_credentials():
    data = load_vault()
    return data.get("email"), data.get("password")


def forget_credentials():
    data = load_vault()
    removed = [data.pop(key, None) for key in ("email", "password")]
    if any(v is not None for v in removed):
        _write(data, get_passphrase())


def save_credentials(email, password):
    update_vault(email=email, password=password)


def load_session():
    return load_vault().get("session")


def save_session(state):
    update_vault(session=state, session_saved_at=datetime.now().isoformat(timespec="seconds"))


def account_info():
    """What the dashboard shows about the saved login. Never returns secrets."""
    data = load_vault() if vault_exists() else {}
    cookies = (data.get("session") or {}).get("cookies", [])
    user = next((c["value"] for c in cookies if c.get("name") == "c_user"), "")
    email = data.get("email") or ""
    if "@" in email:
        name, _, domain = email.partition("@")
        email = f"{name[:2]}***@{domain}"
    elif email:
        email = f"{email[:3]}***"
    return {
        "has_session": bool(cookies),
        "session_saved_at": data.get("session_saved_at", ""),
        "account": f"…{user[-4:]}" if user else "",
        "saved_email": email,
        "has_saved_password": bool(data.get("password")),
    }


def has_session():
    # Only checks the file; reading the session needs the passphrase
    return vault_exists()


def delete_vault():
    if vault_exists():
        os.remove(VAULT_FILE)
