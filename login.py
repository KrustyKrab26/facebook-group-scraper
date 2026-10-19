"""Log in to Facebook once and save the session into the encrypted vault.

Default: opens your installed Chrome/Edge as a *normal* window (not driven by
Playwright) with a separate, temporary profile. You log in and finish 2FA or
any security check there yourself; Meta's verification pages load normally
because nothing is automating the browser while you do it. The script checks
every couple of seconds whether you're logged in, then reads the session
cookies, closes the window and deletes the temporary profile. The dashboard's
Account tab uses the same flow.

    python login.py              # normal browser window (recommended)
    python login.py --playwright # old way: Playwright-driven window, auto-fills stored password

Needs a screen, so run it on your own computer (then copy data/vault.enc to a
server if you deploy there).
"""
import os
import shutil
import socket
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

from config import DATA_DIR
from secret_store import VaultError, get_credentials, save_session, unlock, vault_exists
from utils import find_browser_executable, launch_browser

# Overridable only so the flow can be tested against a local fake login page
LOGIN_URL = os.getenv("LOGIN_URL", "https://www.facebook.com/login")
SESSION_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "facebook.com")
CHALLENGE_PATHS = ("/login", "/checkpoint", "/two_step_verification", "/recover")


def logged_in(state):
    names = {c["name"] for c in state["cookies"]}
    return {"c_user", "xs"} <= names


def wait_for_login(get_state, current_url):
    """Ask the user to press Enter until the browser holds a logged-in session."""
    while True:
        answer = input("Finish logging in (2FA etc.) in the browser, then press Enter here (q to quit)... ")
        if answer.strip().lower() == "q":
            return None
        state = get_state()
        if logged_in(state):
            return state
        print(f"Not logged in yet. The browser is on: {current_url()}")
        print("Complete the step shown there, then press Enter again.")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def browser_login(autofill=None, should_stop=lambda: False, on_status=print, timeout=900):
    """Open a normal browser window on the login page and wait until you're logged in.

    autofill: optional (email, password) typed into the login form for you; you
    still finish any 2FA / security check yourself. Logged in means: the
    session cookies are there and the window has left the login/2FA pages.
    Returns the session, or None if cancelled (should_stop) or timed out.
    Raises RuntimeError if the window is closed first.
    """
    exe = find_browser_executable()
    profile = os.path.join(DATA_DIR, "login-profile")
    shutil.rmtree(profile, ignore_errors=True)
    port = free_port()

    on_status(f"Opening {os.path.basename(exe)}…")
    proc = subprocess.Popen([
        exe, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check", LOGIN_URL,
    ])
    state = None
    try:
        with sync_playwright() as p:
            browser = None
            for _ in range(30):  # give the browser a moment to open its debug port
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    break
                except Exception:
                    time.sleep(0.5)
            if browser is None:
                raise RuntimeError("Couldn't connect to the browser window. Close other windows of it and retry.")
            context = browser.contexts[0]

            if autofill:
                fill_login_form(context, *autofill)
            autofill = None  # don't keep the password around

            last, deadline = None, time.time() + timeout
            while time.time() < deadline:
                if should_stop():
                    on_status("Cancelled.")
                    break
                if not browser.is_connected():
                    raise RuntimeError("The login window was closed before the login finished.")
                try:
                    current = facebook_only(context.storage_state())
                    url = context.pages[-1].url if context.pages else ""
                except Exception:
                    raise RuntimeError("The login window was closed before the login finished.") from None
                if logged_in(current) and not any(p_ in url for p_ in CHALLENGE_PATHS):
                    state = current
                    on_status("Logged in.")
                    break
                message = ("Waiting for you to finish the security check / 2FA in the login window…"
                           if any(p_ in url for p_ in CHALLENGE_PATHS[1:])
                           else "Waiting for you to log in in the window…")
                if message != last:
                    on_status(message)
                    last = message
                time.sleep(2)
            else:
                on_status("Timed out waiting for the login.")
            try:
                browser.new_browser_cdp_session().send("Browser.close")
            except Exception:
                pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        # The profile holds a copy of the cookies; only the encrypted vault should keep them
        for _ in range(30):
            shutil.rmtree(profile, ignore_errors=True)
            if not os.path.exists(profile):
                break
            time.sleep(0.5)
    return state


def fill_login_form(context, email, password):
    """Type the saved email/password into the login form (you press nothing else)."""
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.wait_for_selector("input[name='email']", timeout=15000)
        page.fill("input[name='email']", email)
        page.fill("input[name='pass']", password)
        page.keyboard.press("Enter")
    except Exception:
        pass  # form not found (layout changed or already logged in): just log in by hand


def login_with_normal_browser(url=LOGIN_URL):
    """Terminal version: prints progress; Ctrl+C to give up."""
    try:
        return browser_login()
    except KeyboardInterrupt:
        return None


def facebook_only(state):
    """Drop other sites' cookies (e.g. Edge signs in to your Microsoft account by itself)."""
    return {
        "cookies": [c for c in state["cookies"] if c["domain"].lstrip(".").endswith(SESSION_DOMAIN)],
        "origins": [o for o in state["origins"] if SESSION_DOMAIN in o["origin"]],
    }


def login_with_playwright():
    email = password = None
    if vault_exists():
        email, password = get_credentials()

    with sync_playwright() as p:
        browser = launch_browser(p, headless=False)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        page.goto(LOGIN_URL)

        if email and password:
            try:
                page.fill("input[name='email']", email)
                page.fill("input[name='pass']", password)
                page.keyboard.press("Enter")
                print("Filled in stored credentials.")
            except Exception:
                print("Couldn't find the login form; please log in by hand.")
        del password

        state = wait_for_login(context.storage_state, lambda: page.url)
        browser.close()
    return state


if __name__ == "__main__":
    try:
        if vault_exists():
            unlock()  # ask for the passphrase up front, not after you've logged in
        if "--playwright" in sys.argv:
            state = login_with_playwright()
        else:
            state = login_with_normal_browser()
        if state is None:
            sys.exit("Not saved.")
        save_session(state)
        print("Session saved to the encrypted vault.")
    except (VaultError, RuntimeError) as e:
        sys.exit(str(e))
