"""Start everything with one command:  python start.py
(or double-click start.bat on Windows, run sh start.sh on macOS/Linux)

1. Sets up .venv, packages and the browser the first time.
2. Opens the dashboard; log in from its Account tab (or: python start.py --login).
3. Opens the dashboard, where you change settings and start scrapes.

    python start.py --login   # log in again (e.g. after a checkpoint)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(HERE, ".venv", "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")


def in_venv():
    return os.path.normcase(os.path.abspath(sys.prefix)) == os.path.normcase(os.path.join(HERE, ".venv"))


def ensure_venv():
    """Re-run this script with the project's .venv Python, installing it if needed."""
    if in_venv():
        return
    if not os.path.isfile(VENV_PY):
        print("First run: installing (this takes a few minutes)...\n")
        if subprocess.call([sys.executable, os.path.join(HERE, "install.py")], cwd=HERE) != 0:
            sys.exit("Install failed, see the messages above.")
    sys.exit(subprocess.call([VENV_PY, os.path.abspath(__file__), *sys.argv[1:]], cwd=HERE))


def choose_login():
    from import_session import from_prompt, import_cookies
    from login import login_with_normal_browser
    from secret_store import save_session

    print("\nNo saved Facebook login yet." if "--login" not in sys.argv else "\nLog in again.")
    print("  1) Log in in a browser window (recommended)")
    print("  2) Paste cookies from a browser where you're already logged in")
    print("     (use this if the login window stays on a blank Meta page)")
    choice = ""
    while choice not in ("1", "2"):
        choice = input("Choose 1 or 2: ").strip()

    if choice == "1":
        state = login_with_normal_browser()
        if state is None:
            sys.exit("Not saved.")
        save_session(state)
        print("Session saved to the encrypted vault.")
    else:
        import_cookies(from_prompt())


def main():
    ensure_venv()
    os.chdir(HERE)

    import dashboard
    from secret_store import VaultError, unlock, vault_exists

    try:
        if vault_exists():
            unlock()  # one passphrase prompt for login and dashboard
        # Without a saved login the dashboard opens on its Account tab instead;
        # --login keeps the terminal way
        if "--login" in sys.argv:
            choose_login()
    except VaultError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")

    dashboard.main(open_browser="--no-browser" not in sys.argv)


if __name__ == "__main__":
    main()
