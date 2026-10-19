"""Local dashboard for watching the scraper. Run: python dashboard.py"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import analytics
from config import (
    CHECKPOINT_FILE, DASHBOARD_HOST, DASHBOARD_PORT, LOG_FILE, SCHEMA, STATUS_FILE, STOP_FILE, GroupFiles,
    current_settings, reset_settings, save_settings, validate_settings,
)
from utils import privacy_warnings, clean_saved_files, describe_migration, migrate_legacy_data
import import_session
import login
from secret_store import (
    PASSPHRASE_ENV, VaultError, account_info, forget_credentials, get_credentials, get_passphrase, has_session,
    is_unlocked, save_credentials, save_session, set_passphrase, unlock, vault_exists,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "dashboard.html")

scrape_proc = None


def log_tail(n=300):
    if not os.path.isfile(LOG_FILE):
        return []
    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        return [line.rstrip() for line in f.readlines()[-n:]]


def group_files(slug=None):
    """The group asked for by slug, else the selected one. Always one from the settings list."""
    settings = current_settings()
    for url in settings["GROUPS"]:
        if slug and GroupFiles(url).slug == slug:
            return GroupFiles(url)
    return GroupFiles(settings["SELECTED_GROUP"])


def groups_payload():
    settings = current_settings()
    return {
        "selected": GroupFiles(settings["SELECTED_GROUP"]).slug,
        "scrape_all": settings["SCRAPE_ALL_GROUPS"],
        "groups": [analytics.group_summary(GroupFiles(url)) for url in settings["GROUPS"]],
    }


def stats(slug=None):
    files = group_files(slug)
    status = {}
    if os.path.isfile(STATUS_FILE):
        with open(STATUS_FILE, encoding="utf-8") as f:
            status = json.load(f)

    settings = current_settings()
    return {
        "status": status,
        "process_running": scrape_proc is not None and scrape_proc.poll() is None,
        "has_session": has_session(),
        "unlocked": is_unlocked(),
        "login_state": login_job["state"],
        "group": files.slug,
        "total_posts": len(analytics.read_csv(files.posts)),
        "total_comments": len(analytics.read_csv(files.comments)),
        "total_reactions": sum(int(r.get("total") or 0) for r in analytics.read_csv(files.reactions)),
        "groups": groups_payload(),
        # The dashboard process outlives settings changes, so read them fresh
        "checkpoint_alert": settings["CHECKPOINT_ALERT"],
        "low_risk_mode": settings["LOW_RISK_MODE"],
        # Read fresh: settings.json may have changed since the dashboard started
        "privacy_warning": ("Author names are NOT hashed: real names will be saved." if not settings["ANONYMIZE"]
                            else " ".join(privacy_warnings())),
        "recycle_mb": settings["RECYCLE_MB"],
        "checkpoint": read_checkpoint(),
        "log": log_tail(8),
    }


def scrape_running_elsewhere():
    """status.json says a run is in progress and was updated in the last few minutes."""
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            s = json.load(f)
        recent = datetime.now() - datetime.fromisoformat(s.get("updated_at", "")) < timedelta(minutes=5)
        return s.get("state") in ("starting", "running", "resting") and recent
    except (OSError, ValueError, TypeError):
        return False


def start_scrape():
    global scrape_proc
    if scrape_proc is not None and scrape_proc.poll() is None:
        return False, "A scrape is already running"
    if login_job["state"] == "waiting":
        return False, "Finish or cancel the login in the Account tab first"
    if not has_session():
        return False, "No saved login yet. Log in in the Account tab."
    if not is_unlocked():
        return False, "The vault is locked. Enter your passphrase in the Account tab."
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    # Hand the passphrase to the child through its environment, never a file
    env = dict(os.environ, **{PASSPHRASE_ENV: get_passphrase()})
    scrape_proc = subprocess.Popen([sys.executable, os.path.join(HERE, "main.py")], cwd=HERE, env=env)
    return True, "Scrape started"


# ---- Account: logging in again from the dashboard ----------------------------

login_job = {"state": "idle", "message": "", "started_at": ""}
_login_stop = threading.Event()


def account_payload():
    info = {"vault_exists": vault_exists(), "unlocked": is_unlocked(), "login": dict(login_job)}
    if is_unlocked() and vault_exists():
        try:
            info.update(account_info())
        except VaultError as e:
            info["error"] = str(e)
    return info


def use_passphrase(body):
    """The vault needs a passphrase before anything can be saved in it."""
    if is_unlocked():
        return None
    passphrase = body.get("passphrase") or ""
    if not vault_exists() and passphrase != (body.get("passphrase_confirm") or ""):
        return "The two passphrases don't match."
    try:
        set_passphrase(passphrase)
    except VaultError as e:
        return str(e)
    return None


def save_cookies(body):
    error = use_passphrase(body)
    if error:
        return False, error
    try:
        cookies = (import_session.parse_text(body["text"]) if (body.get("text") or "").strip()
                   else import_session.from_fields(body.get("fields") or {}))
        session = import_session.session_from_cookies(cookies)
        save_session(session)
    except (ValueError, KeyError) as e:
        return False, f"Not saved: {e}"
    except VaultError as e:
        return False, str(e)
    return True, f"Saved {len(session['cookies'])} Facebook cookies. You can start scraping."


def start_browser_login(body):
    if login_job["state"] == "waiting":
        return False, "A login window is already open"
    if scrape_proc is not None and scrape_proc.poll() is None:
        return False, "Wait for the scrape to finish first"
    error = use_passphrase(body)
    if error:
        return False, error

    email, password = (body.get("email") or "").strip(), body.get("password") or ""
    if body.get("use_saved"):
        try:
            email, password = get_credentials()
        except VaultError as e:
            return False, str(e)
        if not (email and password):
            return False, "No saved email and password in the vault"
    if body.get("remember") and email and password and not body.get("use_saved"):
        try:
            save_credentials(email, password)
        except VaultError as e:
            return False, str(e)
    autofill = (email, password) if email and password else None

    def status(message):
        login_job["message"] = message

    def run():
        try:
            session = login.browser_login(autofill=autofill, should_stop=_login_stop.is_set, on_status=status)
            if session:
                save_session(session)
                login_job.update(state="done", message="Logged in and saved. You can start scraping.")
            else:
                login_job.update(state="idle", message=login_job["message"] or "Login cancelled.")
        except Exception as e:  # window closed, no browser found, vault problem...
            login_job.update(state="error", message=str(e))

    _login_stop.clear()
    login_job.update(state="waiting", message="Opening the login window…",
                     started_at=datetime.now().isoformat(timespec="seconds"))
    threading.Thread(target=run, daemon=True).start()
    return True, "Login window opening"


def stop_scrape():
    """Ask the running scrape to stop: it finishes the current scroll, saves, and exits."""
    if scrape_proc is None or scrape_proc.poll() is not None:
        if not scrape_running_elsewhere():
            return False, "No scrape is running"
    with open(STOP_FILE, "w") as f:
        f.write("stop")
    return True, "Stopping after the current scroll…"


def read_checkpoint():
    try:
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def acknowledge_checkpoint():
    data = read_checkpoint()
    if data:
        data["acknowledged"] = True
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def settings_payload():
    schema = {
        key: {k: v for k, v in spec.items() if k != "pattern"}
        for key, spec in SCHEMA.items()
    }
    return {"schema": schema, "values": current_settings()}


class Handler(BaseHTTPRequestHandler):
    def same_origin_json(self):
        """Block other websites from driving the dashboard (CSRF).

        A page on another site can't send application/json cross-origin without
        a CORS preflight, which this server never approves; the Origin check
        covers browsers that send one.
        """
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            with open(PAGE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")  # always the latest page after an update
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/stats":
            self.send_json(stats(query.get("group")))
        elif url.path == "/api/posts":
            def num(key, default, hi):
                try:
                    return max(0, min(hi, int(query.get(key, default))))
                except ValueError:
                    return default
            self.send_json(analytics.list_posts(group_files(query.get("group")), query.get("q", "").strip(),
                                                query.get("sort", "newest"),
                                                num("offset", 0, 10**6), num("limit", 20, 100)))
        elif url.path == "/api/analytics":
            self.send_json(analytics.analytics(group_files(query.get("group"))))
        elif url.path == "/api/account":
            self.send_json(account_payload())
        elif url.path == "/api/log":
            self.send_json({"lines": log_tail(1000)})
        elif url.path == "/api/settings":
            self.send_json(settings_payload())
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.same_origin_json():
            return self.send_json({"ok": False, "message": "Rejected"}, 403)
        if self.path == "/api/settings":
            body = self.read_json()
            if body.get("reset"):
                reset_settings()
                return self.send_json({"ok": True, "message": "Reset to .env defaults", **settings_payload()})
            clean, errors = validate_settings(body.get("values", {}))
            if errors:
                return self.send_json({"ok": False, "errors": errors, "message": "Fix the highlighted fields"}, 400)
            save_settings(clean)
            running = scrape_proc is not None and scrape_proc.poll() is None
            message = "Saved. Applies to the next run." if running else "Saved."
            self.send_json({"ok": True, "message": message, **settings_payload()})
        elif self.path == "/api/checkpoint/ack":
            acknowledge_checkpoint()
            self.send_json({"ok": True})
        elif self.path == "/api/stop":
            ok, message = stop_scrape()
            self.send_json({"ok": ok, "message": message}, 200 if ok else 409)
        elif self.path == "/api/run":
            ok, message = start_scrape()
            self.send_json({"ok": ok, "message": message}, 200 if ok else 409)
        elif self.path.startswith("/api/account/"):
            body = self.read_json()
            action = self.path.rsplit("/", 1)[-1]
            if action == "unlock":
                error = use_passphrase(body)
                ok, message = (False, error) if error else (True, "Unlocked")
            elif action == "cookies":
                ok, message = save_cookies(body)
            elif action == "login":
                ok, message = start_browser_login(body)
            elif action == "cancel":
                _login_stop.set()
                ok, message = True, "Cancelling…"
            elif action == "forget-password":
                try:
                    forget_credentials()
                    ok, message = True, "Saved email and password removed"
                except VaultError as e:
                    ok, message = False, str(e)
            else:
                return self.send_error(404)
            # Never echo anything back from the request: it may hold secrets
            self.send_json({"ok": ok, "message": message, **account_payload()}, 200 if ok else 400)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # keep the terminal quiet; the page polls every few seconds


def main(open_browser=True, prompt=True):
    os.chdir(HERE)
    # A scrape started elsewhere may be writing the CSVs; it cleans them itself then
    if not scrape_running_elsewhere():
        for line in describe_migration(migrate_legacy_data()):
            print(line)
        for url in current_settings()["GROUPS"]:
            for name, n in clean_saved_files(GroupFiles(url)).items():
                print(f"Removed 'Xem thêm'/'Ẩn bớt' button text from {n} rows of {name} (backup: {name}.bak)")
    if has_session() and prompt:
        try:
            unlock()
        except VaultError as e:
            # Keep going: the passphrase can be entered in the Account tab
            print(f"{e} The vault stays locked until you unlock it in the Account tab.")
    else:
        print("No saved login yet: log in from the dashboard's Account tab.")

    url = f"http://localhost:{DASHBOARD_PORT}" + ("" if has_session() else "/#account")
    try:
        server = ThreadingHTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), Handler)
    except OSError:
        sys.exit(f"Port {DASHBOARD_PORT} is busy: the dashboard may already be open at {url}. "
                 "Close the other one or set DASHBOARD_PORT in .env.")
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")


if __name__ == "__main__":
    # --no-prompt: don't ask for the passphrase in the terminal (unlock in the Account tab)
    main(open_browser="--no-browser" not in sys.argv, prompt="--no-prompt" not in sys.argv)
