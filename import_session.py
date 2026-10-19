"""Import a Facebook session from a browser where you're already logged in.

Use this when login.py gets stuck on Meta's verification page. Log in to
Facebook normally in a browser where it works, then either:

    python import_session.py --manual        # paste the cookies from DevTools (no extension needed)
    python import_session.py cookies.json    # or a file exported by a cookie extension

Both Cookie-Editor style JSON and Netscape cookies.txt files work. Only
facebook.com cookies are kept, and they go straight into the encrypted vault.
"""
import json
import os
import sys
from getpass import getpass

from secret_store import VaultError, save_session, unlock, vault_exists

SAME_SITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}


def is_facebook(domain):
    return domain.lstrip(".").endswith("facebook.com")


def cookie(name, value, domain=".facebook.com", path="/", expires=-1,
           http_only=True, secure=True, same_site="None"):
    return {"name": name, "value": value, "domain": domain, "path": path,
            "expires": expires, "httpOnly": http_only, "secure": secure, "sameSite": same_site}


def parse_json(text):
    data = json.loads(text)
    if isinstance(data, dict):  # Playwright storage_state or {"cookies": [...]}
        data = data.get("cookies", [])
    cookies = []
    for c in data:
        expires = c.get("expirationDate", c.get("expires", -1))
        same_site = str(c.get("sameSite") or "lax").lower()
        cookies.append(cookie(
            c["name"], c["value"], c.get("domain", ".facebook.com"), c.get("path", "/"),
            float(expires) if expires not in (None, "") else -1,
            bool(c.get("httpOnly", False)), bool(c.get("secure", True)),
            SAME_SITE.get(same_site, "Lax"),
        ))
    return cookies


def parse_netscape(text):
    cookies = []
    for line in text.splitlines():
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, path, secure, expires, name, value = parts[:7]
        cookies.append(cookie(name, value.strip(), domain, path,
                              float(expires) if expires.strip() not in ("", "0") else -1,
                              http_only, secure.upper() == "TRUE"))
    return cookies


def parse_header(text):
    """'c_user=123; xs=abc; datr=…' as copied from a request's Cookie header."""
    cookies = []
    for part in text.replace("\n", ";").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name.strip() and value.strip():
            name = name.strip()
            cookies.append(cookie(name, value.strip(), http_only=name != "c_user"))
    return cookies


def parse_text(text):
    """Any of: exported JSON, cookies.txt, or a 'name=value; name=value' string."""
    text = (text or "").strip().lstrip("﻿")
    if text.startswith(("[", "{")):
        return parse_json(text)
    if "\t" in text:
        return parse_netscape(text)
    return parse_header(text)


def from_fields(fields):
    """Values typed into separate boxes: {"c_user": ..., "xs": ..., "datr": ...}."""
    return [cookie(name, str(value).strip(), http_only=name != "c_user")
            for name, value in fields.items() if name in COOKIE_NAMES and str(value or "").strip()]


COOKIE_NAMES = ("c_user", "xs", "datr", "fr", "sb")


def session_from_cookies(cookies):
    """Keep facebook.com cookies and check they're a logged-in session. Raises ValueError."""
    cookies = [c for c in cookies if is_facebook(c["domain"])]
    names = {c["name"] for c in cookies}
    missing = [n for n in ("c_user", "xs") if n not in names]
    if missing:
        raise ValueError(f"No logged-in Facebook session: {' and '.join(missing)} missing. "
                         "Copy them while you're logged in to Facebook.")
    user = next(c["value"] for c in cookies if c["name"] == "c_user")
    if not user.isdigit():
        raise ValueError("c_user should be your numeric account id; check you copied the Value column.")
    return {"cookies": cookies, "origins": []}


def from_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return parse_text(f.read())


def from_prompt():
    print("In the browser where you're logged in to Facebook: press F12, open")
    print("Application (Edge/Chrome) or Storage (Firefox) > Cookies > https://www.facebook.com,")
    print("and copy the Value column for each name below.\n")
    cookies = []
    for name, required in (("c_user", True), ("xs", True), ("datr", False), ("fr", False), ("sb", False)):
        prompt = f"{name}{'' if required else ' (optional, Enter to skip)'}: "
        # xs is the actual session secret, so don't echo it
        value = (getpass(prompt) if name == "xs" else input(prompt)).strip()
        if value:
            cookies.append(cookie(name, value, http_only=name != "c_user"))
        elif required:
            sys.exit(f"{name} is required.")
    return cookies


def import_cookies(cookies):
    """Keep facebook.com cookies, check they're a logged-in session, save to the vault."""
    try:
        session = session_from_cookies(cookies)
    except ValueError as e:
        sys.exit(str(e))
    save_session(session)
    print(f"Imported {len(session['cookies'])} facebook.com cookies into the encrypted vault.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--manual" not in sys.argv and not args:
        sys.exit(__doc__)

    try:
        if vault_exists():
            unlock()
        import_cookies(from_prompt() if "--manual" in sys.argv else from_file(args[0]))
    except (VaultError, OSError, ValueError, KeyError) as e:
        sys.exit(f"Import failed: {e}")

    if args:
        print(f"\n{args[0]} contains your live Facebook session in plain text.")
        if input("Delete it now? [Y/n] ").strip().lower() in ("", "y", "yes"):
            os.remove(args[0])
            print("Deleted.")
    print("\nDon't press 'Log out' in that browser: it would end this session too. Just close the tab.")
