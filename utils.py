import csv
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime

from config import (
    ANONYMIZE, BROWSER_CHANNEL, CHECKPOINT_FILE, DATA_DIR, GROUPS, HASH_SALT, LOG_FILE, STATUS_FILE, GroupFiles,
)
from reactions import TYPES as REACTION_TYPES

# Windows consoles default to a legacy code page that can't print Vietnamese
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FIELDS = ["post_id", "author", "time_text", "text", "scraped_at"]
COMMENT_FIELDS = ["post_id", "comment_index", "author", "text", "scraped_at"]
# updated_at: when "update saved posts" last refreshed the row (empty = never)
# comment_count / share_count: the post's real totals from Facebook (empty = unknown)
REACTION_FIELDS = ["post_id", "total", *REACTION_TYPES, "comment_count", "share_count",
                   "source", "scraped_at", "updated_at"]


# Flags that cut memory without changing what pages see: no sound, no video
# autoplay, no background extras.
BROWSER_ARGS = [
    "--mute-audio",
    "--autoplay-policy=user-gesture-required",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
]


def launch_browser(playwright, headless):
    """Launch Playwright's Chromium, or fall back to an installed Chrome / Edge.

    Some PCs refuse to run the bundled Chromium (antivirus or app-control
    policies block unsigned browsers); real Chrome/Edge are signed and still work.
    """
    if BROWSER_CHANNEL:
        choices = [None if BROWSER_CHANNEL == "chromium" else BROWSER_CHANNEL]
    else:
        choices = [None, "chrome", "msedge"]

    errors = []
    for channel in choices:
        try:
            browser = playwright.chromium.launch(headless=headless, channel=channel, args=BROWSER_ARGS)
            print(f"Using browser: {channel or 'Playwright Chromium'} {browser.version}")
            return browser
        except Exception as e:
            errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
    raise RuntimeError("No browser could be started. Run install.py, or install Google Chrome.\n  "
                       + "\n  ".join(errors))


_BROWSER_PATHS = {
    "chrome": {
        "win32": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                  r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                  r"%LocalAppData%\Google\Chrome\Application\chrome.exe"],
        "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    },
    "msedge": {
        "win32": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                  r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
        "darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        "linux": ["microsoft-edge", "microsoft-edge-stable"],
    },
}


def find_browser_executable():
    """Path to an installed Chrome or Edge (BROWSER_CHANNEL picks which first)."""
    order = ["chrome", "msedge"]
    if BROWSER_CHANNEL in order:
        order.remove(BROWSER_CHANNEL)
        order.insert(0, BROWSER_CHANNEL)

    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    for name in order:
        for candidate in _BROWSER_PATHS[name].get(platform, []):
            path = os.path.expandvars(candidate) if os.sep in candidate else shutil.which(candidate)
            if path and os.path.isfile(path):
                return path
    raise RuntimeError("Couldn't find Google Chrome or Microsoft Edge. Install one of them, "
                       "or use: python login.py --playwright")


def log_message(message):
    line = f"{datetime.now()} - {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# Salts that come with the project or its examples: hashes made with them can
# be reversed by anyone who tries names from the group's member list
PLACEHOLDER_SALTS = {"", "change-me", "pick-any-random-string", "your-secret-salt"}


def privacy_warnings():
    """Reasons author names aren't properly protected (empty list = fine)."""
    if not ANONYMIZE:
        return ["Author names are NOT hashed: real names are being saved. Turn 'Hash author names' "
                "back on unless the people in the group agreed to this."]
    if HASH_SALT.strip() in PLACEHOLDER_SALTS or len(HASH_SALT.strip()) < 8:
        return ["HASH_SALT is a placeholder or too short, so hashed names could be guessed. "
                "Put a long random value in .env (e.g. python -c \"import secrets; print(secrets.token_hex(16))\") "
                "before collecting data, and keep it private."]
    return []


def anonymize(name):
    if not name or not ANONYMIZE:
        return name
    return "user_" + hashlib.sha256((HASH_SALT + name).encode("utf-8")).hexdigest()[:12]


def load_existing_ids(files):
    return {row["post_id"] for row in read_rows(files.posts)}


def migrate_legacy_data():
    """Older versions kept one group's CSVs directly in data/. Move them into
    data/groups/<that group>/ the first time this version runs."""
    legacy = [n for n in ("posts.csv", "comments.csv", "reactions.csv",
                          "posts.csv.bak", "comments.csv.bak") if os.path.isfile(os.path.join(DATA_DIR, n))]
    if not legacy:
        return None
    target = GroupFiles(GROUPS[0])
    os.makedirs(target.dir, exist_ok=True)
    moved, kept = [], []
    for name in legacy:
        dest = os.path.join(target.dir, name)
        if os.path.exists(dest):
            kept.append(name)  # never overwrite; leave the old file where it is
            continue
        os.replace(os.path.join(DATA_DIR, name), dest)
        moved.append(name)
    return {"group": target.slug, "moved": moved, "kept": kept}


def describe_migration(result):
    """Log lines for migrate_legacy_data()'s result."""
    if not result:
        return []
    lines = []
    if result["moved"]:
        lines.append(f"Moved {', '.join(result['moved'])} from data/ into data/groups/{result['group']}/")
    if result["kept"]:
        lines.append(f"Left {', '.join(result['kept'])} in data/: data/groups/{result['group']}/ already has "
                     "files with those names. Merge them by hand if you need the old rows.")
    return lines


def write_status(status):
    """Write live progress for the dashboard (atomic, so it never reads half a file)."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False)
    os.replace(tmp, STATUS_FILE)


def read_rows(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_rows(path, fields, rows):
    """Rewrite a whole CSV atomically."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def _ensure_header(path, fields):
    """Files from older versions may lack newer columns: add them (empty)."""
    if not os.path.isfile(path):
        return
    with open(path, newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f), None)
    if header and header != fields:
        _write_rows(path, fields, read_rows(path))


def _append_csv(path, fields, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _ensure_header(path, fields)
    file_exists = os.path.isfile(path)

    # utf-8-sig so Excel shows Vietnamese characters correctly
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def record_checkpoint(message):
    """Remember that Facebook blocked or challenged us, for the dashboard warning."""
    data = {"at": datetime.now().isoformat(timespec="seconds"), "message": message, "acknowledged": False}
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def save_posts_to_csv(files, posts):
    _append_csv(files.posts, FIELDS, posts)


def save_comments_to_csv(files, comments):
    _append_csv(files.comments, COMMENT_FIELDS, comments)


def save_reactions_to_csv(files, rows):
    _append_csv(files.reactions, REACTION_FIELDS, rows)


def load_saved_engagement(files):
    """For updating saved posts: {post_id: reaction row} and {post_id: [comments]}."""
    reacts = {r["post_id"]: r for r in read_rows(files.reactions)}
    comments = {}
    for c in read_rows(files.comments):
        comments.setdefault(c["post_id"], []).append(c)
    return reacts, comments


_BUTTON_LINE = re.compile(r"^\s*(xem thêm|ẩn bớt|see more|see less)\s*$", re.I)
_TRAILING_LESS = re.compile(r"\s*(ẩn bớt|see less)\s*$", re.I)
_TRAILING_MORE = re.compile(r"(…|\.\.\.)\s*(xem thêm|see more)\s*$", re.I)


def clean_text(text):
    """Remove Facebook's "Xem thêm"/"Ẩn bớt" button labels (same rules as cleanText in scraper.py).

    A cut-off comment keeps its "…" so it's clear the text is incomplete.
    """
    lines = [l for l in (text or "").split("\n") if not _BUTTON_LINE.match(l)]
    text = _TRAILING_LESS.sub("", "\n".join(lines))
    return _TRAILING_MORE.sub("…", text).strip()


def clean_saved_files(files):
    """Fix text saved by older versions that kept the button labels. Backs up first.

    Returns {file name: rows fixed}. Safe to run any number of times.
    """
    fixed = {}
    for path, fields in ((files.posts, FIELDS), (files.comments, COMMENT_FIELDS)):
        rows = read_rows(path)
        changed = 0
        for r in rows:
            clean = clean_text(r.get("text", ""))
            if clean != r.get("text", ""):
                r["text"] = clean
                changed += 1
        if changed:
            backup = path + ".bak"
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
            _write_rows(path, fields, rows)
            fixed[f"{files.slug}/{os.path.basename(path)}"] = changed
    return fixed


def update_comment_texts(files, fixes):
    """Replace the text of saved comments: {(post_id, comment_index): full text}."""
    if not fixes:
        return
    rows = read_rows(files.comments)
    for r in rows:
        new = fixes.get((r["post_id"], str(r["comment_index"])))
        if new is not None:
            r["text"] = new
    _write_rows(files.comments, COMMENT_FIELDS, rows)


def update_reactions_csv(files, updated):
    """Replace the rows of posts in `updated` ({post_id: row}); add ones not in the file yet."""
    if not updated:
        return
    rows = read_rows(files.reactions)
    have = set()
    for i, r in enumerate(rows):
        if r["post_id"] in updated:
            rows[i] = updated[r["post_id"]]
            have.add(r["post_id"])
    rows += [r for pid, r in updated.items() if pid not in have]
    os.makedirs(files.dir, exist_ok=True)
    _write_rows(files.reactions, REACTION_FIELDS, rows)
