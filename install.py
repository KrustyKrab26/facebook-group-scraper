"""One-step setup on Windows, macOS or Linux:  python install.py

Creates .venv, installs the Python packages and Playwright's Chromium,
and copies .env.example to .env if you don't have one yet.
"""
import os
import shutil
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
BIN = os.path.join(VENV, "Scripts" if os.name == "nt" else "bin")
PY = os.path.join(BIN, "python.exe" if os.name == "nt" else "python")


def run(*args):
    print("+", " ".join(args))
    subprocess.check_call(args, cwd=HERE)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required.")

    if not os.path.isfile(PY):
        print("Creating virtual environment in .venv")
        venv.create(VENV, with_pip=True)

    run(PY, "-m", "pip", "install", "--upgrade", "pip")
    run(PY, "-m", "pip", "install", "-r", "requirements.txt")
    # --force repairs a half-deleted browser (e.g. antivirus removed chrome.exe)
    run(PY, "-m", "playwright", "install", "--force", "chromium")
    if sys.platform.startswith("linux"):
        print("\nOn Linux, if Chromium fails to start, install its system libraries with:")
        print(f"  sudo {PY} -m playwright install-deps chromium")

    env_file = os.path.join(HERE, ".env")
    if not os.path.isfile(env_file):
        shutil.copy(os.path.join(HERE, ".env.example"), env_file)
        print("\nCreated .env from .env.example. Edit it and set your own HASH_SALT.")

    py = os.path.relpath(PY, HERE)
    print(f"""
Done. Next steps:
  {py} set_credentials.py   # optional: store your Facebook login in the encrypted vault
  {py} login.py             # log in once and save the session
  {py} dashboard.py         # open the dashboard at http://localhost:8765
""")
