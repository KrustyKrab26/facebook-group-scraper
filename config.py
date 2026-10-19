import json
import os
import re

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Everything the scraper writes lives here (mount this folder as a volume in Docker)
DATA_DIR = os.path.abspath(os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data")))
# Each group gets its own folder: data/groups/<slug>/posts.csv, comments.csv, reactions.csv
GROUPS_DIR = os.path.join(DATA_DIR, "groups")
# Last checkpoint Facebook showed, for the dashboard warning
CHECKPOINT_FILE = os.path.join(DATA_DIR, "checkpoint.json")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
LOG_FILE = os.path.join(DATA_DIR, "logs.txt")
# Settings changed from the dashboard; they win over .env
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
# Created by the dashboard's Stop button; the scraper stops at the next scroll
STOP_FILE = os.path.join(DATA_DIR, "stop.flag")
# Passphrase-encrypted email, password and login session
VAULT_FILE = os.path.join(DATA_DIR, "vault.enc")

os.makedirs(DATA_DIR, exist_ok=True)

# What low-risk mode enforces, whatever the other settings say
LOW_RISK_MODE_MAX_POSTS = 30
LOW_RISK_MODE_MIN_DELAY = 5
LOW_RISK_MODE_MAX_DELAY = 12

GROUP_URL = re.compile(r"^https://(www\.|m\.)?facebook\.com/groups/[^/?#\s]+/?$")
# Placeholder: put your own group(s) in Settings or .env
DEFAULT_GROUP = "https://www.facebook.com/groups/your-group-name"
MAX_GROUPS = 20


def group_slug(url):
    """Folder name for a group: the part after /groups/ (or the file name for local test pages)."""
    m = re.search(r"/groups/([^/?#]+)", url or "")
    name = m.group(1) if m else os.path.splitext(os.path.basename((url or "").rstrip("/")))[0]
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "group"


class GroupFiles:
    """Where one group's data lives."""

    def __init__(self, url):
        self.url = url
        self.slug = group_slug(url)
        self.dir = os.path.join(GROUPS_DIR, self.slug)
        self.posts = os.path.join(self.dir, "posts.csv")
        self.comments = os.path.join(self.dir, "comments.csv")
        self.reactions = os.path.join(self.dir, "reactions.csv")

    def __repr__(self):
        return f"GroupFiles({self.slug})"

# Settings the dashboard can edit. Each value comes from settings.json, else
# .env / environment, else the default here. "disabled_when" greys a field out
# in the dashboard while another setting has the given value; "note_when" shows
# a hint under the field instead (e.g. what low-risk mode overrides).
SCHEMA = {
    "GROUPS": dict(type="list", default=[DEFAULT_GROUP], group="Groups",
                   label=f"Groups to scrape, one URL per line (max {MAX_GROUPS})", pattern=GROUP_URL),
    # Picked from the header's group menu, not shown as a field
    "SELECTED_GROUP": dict(type="str", default="", group="Groups", label="Selected group", hidden=True),
    "SCRAPE_ALL_GROUPS": dict(type="bool", default=False, group="Groups",
                              label="Start scrape goes through every group in the list, one after another"),
    "GROUP_PAUSE_MIN": dict(type="float", default=3, min=0.5, max=60, group="Groups",
                            label="Pause between groups (minutes)", disabled_when=[["SCRAPE_ALL_GROUPS", False]]),
    # Newest posts first instead of Facebook's "relevant" ordering
    "SORT_CHRONOLOGICAL": dict(type="bool", default=True, group="Groups", label="Newest posts first"),

    "LOW_RISK_MODE": dict(type="bool", default=False, group="Safety",
                       label=f"Low-risk mode: at most {LOW_RISK_MODE_MAX_POSTS} posts, "
                             f"{LOW_RISK_MODE_MIN_DELAY}-{LOW_RISK_MODE_MAX_DELAY}s pauses, no extra clicks"),
    "CHECKPOINT_ALERT": dict(type="bool", default=True, group="Safety",
                             label="Warn me when Facebook shows a checkpoint"),

    "MAX_POSTS": dict(type="int", default=100, min=1, max=500, group="Limits",
                      label="Max new posts per run",
                      note_when=[["LOW_RISK_MODE", True, f"Capped at {LOW_RISK_MODE_MAX_POSTS} while low-risk mode is on"],
                                 ["BATCH_MODE", True, "Not used in batch mode: see Speed & batches"]],
                      disabled_when=[["BATCH_MODE", True]]),
    # Each run scrolls past posts saved earlier; auto mode sizes the run from
    # how many are saved and how fast the feed is loading
    "AUTO_SCROLL_LIMIT": dict(type="bool", default=True, group="Limits",
                              label="Auto-adjust scrolls to reach unsaved posts"),
    "SCROLL_LIMIT": dict(type="int", default=40, min=1, max=300, group="Limits",
                         label="Max scrolls per run (when auto is off)",
                         disabled_when=[["AUTO_SCROLL_LIMIT", True]]),
    "MAX_IDLE_SCROLLS": dict(type="int", default=4, min=1, max=20, group="Limits",
                             label="Stop after N scrolls where the feed loads nothing"),
    "MIN_DELAY": dict(type="float", default=3, min=1, max=60, group="Limits", label="Min pause between scrolls (s)",
                      note_when=[["LOW_RISK_MODE", True, f"At least {LOW_RISK_MODE_MIN_DELAY}s while low-risk mode is on"]]),
    "MAX_DELAY": dict(type="float", default=7, min=1, max=120, group="Limits", label="Max pause between scrolls (s)",
                      note_when=[["LOW_RISK_MODE", True, f"At least {LOW_RISK_MODE_MAX_DELAY}s while low-risk mode is on"]]),

    # Each run starts at the newest post and has to pass the saved ones first
    "FAST_FORWARD": dict(type="bool", default=True, group="Speed & batches",
                         label="a. Scroll quickly past posts that are already saved (1-2 s pauses)"),
    "SKIP_SEE_MORE_SAVED": dict(type="bool", default=True, group="Speed & batches",
                                label="b. Don't click \"Xem thêm\" on posts that are already saved"),
    "BATCH_MODE": dict(type="bool", default=False, group="Speed & batches",
                       label="c. Scrape in batches: rest between batches with the page kept open, "
                             "then continue where it stopped"),
    "BATCH_POSTS": dict(type="int", default=30, min=1, max=500, group="Speed & batches",
                        label="New posts per batch", disabled_when=[["BATCH_MODE", False]],
                        note_when=[["LOW_RISK_MODE", True, f"Capped at {LOW_RISK_MODE_MAX_POSTS} while low-risk mode is on"]]),
    "BATCH_TOTAL": dict(type="int", default=150, min=1, max=5000, group="Speed & batches",
                        label="Stop after this many new posts in total", disabled_when=[["BATCH_MODE", False]]),
    "BATCH_REST_MIN": dict(type="float", default=120, min=5, max=1440, group="Speed & batches",
                           label="Rest between batches (minutes)", disabled_when=[["BATCH_MODE", False]]),

    # Posts show 1-2 comments in the feed; to reach the limit the scraper
    # clicks "View more comments" once per post
    "COLLECT_COMMENTS": dict(type="bool", default=True, group="Comments", label="Scrape comments"),
    "MAX_COMMENTS_PER_POST": dict(type="int", default=3, min=1, max=5, group="Comments",
                                  label="Comments per post (1-5)", disabled_when=[["COLLECT_COMMENTS", False]]),
    "EXPAND_COMMENTS": dict(type="bool", default=True, group="Comments",
                            label='Click "View more comments" when needed',
                            disabled_when=[["COLLECT_COMMENTS", False], ["LOW_RISK_MODE", True]]),

    # The bar under a post shows the top 3 reaction types; the popup has every type
    "COLLECT_REACTIONS": dict(type="bool", default=True, group="Reactions", label="Scrape reactions"),
    "EXPAND_REACTIONS": dict(type="bool", default=True, group="Reactions",
                             label="Open the reactions popup for every type's count",
                             disabled_when=[["COLLECT_REACTIONS", False], ["LOW_RISK_MODE", True]]),

    # Posts saved in earlier runs scroll past again; their counts can be refreshed
    "UPDATE_SAVED": dict(type="bool", default=False, group="Saved posts",
                         label="Update reactions and comments of saved posts as the scraper scrolls past them"),
    "UPDATE_SAVED_CLICKS": dict(type="bool", default=False, group="Saved posts",
                                label="Also open the popups for saved posts (up to 2 extra clicks per post)",
                                disabled_when=[["UPDATE_SAVED", False], ["LOW_RISK_MODE", True]]),

    # Memory: Facebook's feed keeps images and videos loaded as you scroll
    "BLOCK_MEDIA": dict(type="bool", default=True, group="Performance",
                        label="Don't load images, videos and fonts (much less RAM and data)"),
    "RECYCLE_MB": dict(type="int", default=1200, min=0, max=8000, group="Performance",
                       label="Reopen the page when its memory goes above (MB, 0 = never)"),

    "BROWSER_CHANNEL": dict(type="choice", default="", choices=["", "chromium", "chrome", "msedge"],
                            group="Browser", label="Browser"),
    "HEADLESS": dict(type="bool", default=False, group="Browser", label="Hide browser window"),

    # Replace author names with a salted hash so the dataset holds no names
    "ANONYMIZE": dict(type="bool", default=True, group="Privacy",
                      label="Hash author names before saving (keep this on)",
                      note_when=[["ANONYMIZE", False, "Real names will be saved. Only do this with the "
                                                      "people's consent."]]),
}


def _convert(key, raw):
    spec = SCHEMA[key]
    kind = spec["type"]
    if kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(float(raw))
    if kind == "float":
        return float(raw)
    if kind == "list":
        items = raw if isinstance(raw, list) else re.split(r"[\s,]+", str(raw))
        out = []
        for item in (str(i).strip().rstrip("/") for i in items):
            if item and item not in out:
                out.append(item)
        return out
    return str(raw).strip()


def _read_settings_file():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def current_settings():
    saved = _read_settings_file()
    # Older versions had one TARGET_GROUP instead of a list
    legacy_group = saved.get("TARGET_GROUP", os.getenv("TARGET_GROUP"))
    if legacy_group and "GROUPS" not in saved and os.getenv("GROUPS") is None:
        saved["GROUPS"] = [legacy_group]
    # Older versions called low-risk mode "light mode"
    legacy = saved.get("LIGHT_MODE", os.getenv("LIGHT_MODE"))
    if legacy is not None and "LOW_RISK_MODE" not in saved and os.getenv("LOW_RISK_MODE") is None:
        saved["LOW_RISK_MODE"] = legacy
    # Older versions turned comments off with "0 comments per post"
    if str(saved.get("MAX_COMMENTS_PER_POST", os.getenv("MAX_COMMENTS_PER_POST"))) == "0"             and "COLLECT_COMMENTS" not in saved and os.getenv("COLLECT_COMMENTS") is None:
        saved["COLLECT_COMMENTS"] = False
    values = {}
    for key, spec in SCHEMA.items():
        raw = saved.get(key, os.getenv(key))
        try:
            value = spec["default"] if raw is None or raw == "" and spec["type"] != "choice" else _convert(key, raw)
        except (TypeError, ValueError):
            value = spec["default"]
        if spec["type"] in ("int", "float"):
            value = max(spec["min"], min(spec["max"], value))
        if spec["type"] == "choice" and value not in spec["choices"]:
            value = spec["default"]
        if spec["type"] == "list" and not value:
            value = list(spec["default"])
        values[key] = value
    # The selected group must be one of the list
    if values["SELECTED_GROUP"] not in values["GROUPS"]:
        values["SELECTED_GROUP"] = values["GROUPS"][0]
    return values


def validate_settings(updates):
    """Return (clean_values, errors) for a dict of submitted settings."""
    clean, errors = {}, {}
    for key, raw in updates.items():
        if key not in SCHEMA:
            continue
        spec = SCHEMA[key]
        try:
            value = _convert(key, raw)
        except (TypeError, ValueError):
            errors[key] = "Not a valid number"
            continue
        if spec["type"] in ("int", "float") and not spec["min"] <= value <= spec["max"]:
            errors[key] = f"Must be between {spec['min']} and {spec['max']}"
        elif spec["type"] == "choice" and value not in spec["choices"]:
            errors[key] = "Not a valid choice"
        elif spec["type"] == "list":
            bad = [v for v in value if not spec["pattern"].match(v)]
            if not value:
                errors[key] = "Add at least one group"
            elif bad:
                errors[key] = f"Not a group URL: {bad[0]} (use https://www.facebook.com/groups/<name>)"
            elif len(value) > MAX_GROUPS:
                errors[key] = f"At most {MAX_GROUPS} groups"
            elif len({group_slug(v) for v in value}) < len(value):
                errors[key] = "Two URLs point to the same group"
            else:
                clean[key] = value
        elif "pattern" in spec and not spec["pattern"].match(value):
            errors[key] = "Must look like https://www.facebook.com/groups/<name>"
        else:
            clean[key] = value

    merged = {**current_settings(), **clean}
    if merged["MIN_DELAY"] > merged["MAX_DELAY"]:
        errors["MAX_DELAY"] = "Must be at least the min pause"
    if "SELECTED_GROUP" in clean and clean["SELECTED_GROUP"] not in merged["GROUPS"]:
        errors["SELECTED_GROUP"] = "Not one of the groups in the list"
    return clean, errors


def save_settings(clean):
    data = {**_read_settings_file(), **clean}
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def reset_settings():
    if os.path.isfile(SETTINGS_FILE):
        os.remove(SETTINGS_FILE)


def effective_settings():
    """Settings as a run uses them: switched-off features and low-risk mode applied."""
    s = current_settings()
    if not s["COLLECT_COMMENTS"]:
        s["MAX_COMMENTS_PER_POST"] = 0
        s["EXPAND_COMMENTS"] = False
    if not s["COLLECT_REACTIONS"]:
        s["EXPAND_REACTIONS"] = False
    s["MAX_DELAY"] = max(s["MIN_DELAY"], s["MAX_DELAY"])
    if s["LOW_RISK_MODE"]:
        s["MAX_POSTS"] = min(s["MAX_POSTS"], LOW_RISK_MODE_MAX_POSTS)
        s["BATCH_POSTS"] = min(s["BATCH_POSTS"], LOW_RISK_MODE_MAX_POSTS)
        s["MIN_DELAY"] = max(s["MIN_DELAY"], LOW_RISK_MODE_MIN_DELAY)
        s["MAX_DELAY"] = max(s["MAX_DELAY"], LOW_RISK_MODE_MAX_DELAY)
        s["EXPAND_COMMENTS"] = False
        s["EXPAND_REACTIONS"] = False
        s["UPDATE_SAVED_CLICKS"] = False
    if not s["UPDATE_SAVED"]:
        s["UPDATE_SAVED_CLICKS"] = False
    return s


_s = effective_settings()
GROUPS = _s["GROUPS"]
SELECTED_GROUP = _s["SELECTED_GROUP"]
SCRAPE_ALL_GROUPS = _s["SCRAPE_ALL_GROUPS"]
GROUP_PAUSE_MIN = _s["GROUP_PAUSE_MIN"]
BLOCK_MEDIA = _s["BLOCK_MEDIA"]
FAST_FORWARD = _s["FAST_FORWARD"]
SKIP_SEE_MORE_SAVED = _s["SKIP_SEE_MORE_SAVED"]
BATCH_MODE = _s["BATCH_MODE"]
BATCH_POSTS = _s["BATCH_POSTS"]
BATCH_TOTAL = _s["BATCH_TOTAL"]
BATCH_REST_MIN = _s["BATCH_REST_MIN"]
RECYCLE_MB = _s["RECYCLE_MB"]
SORT_CHRONOLOGICAL = _s["SORT_CHRONOLOGICAL"]
MAX_POSTS = _s["MAX_POSTS"]
SCROLL_LIMIT = _s["SCROLL_LIMIT"]
AUTO_SCROLL_LIMIT = _s["AUTO_SCROLL_LIMIT"]
# Hard ceiling for auto mode, so a run can never scroll forever
AUTO_SCROLL_CAP = SCHEMA["SCROLL_LIMIT"]["max"]
MAX_IDLE_SCROLLS = _s["MAX_IDLE_SCROLLS"]
MIN_DELAY = _s["MIN_DELAY"]
MAX_DELAY = _s["MAX_DELAY"]
MAX_COMMENTS_PER_POST = _s["MAX_COMMENTS_PER_POST"]
EXPAND_COMMENTS = _s["EXPAND_COMMENTS"]
COLLECT_REACTIONS = _s["COLLECT_REACTIONS"]
LOW_RISK_MODE = _s["LOW_RISK_MODE"]
UPDATE_SAVED = _s["UPDATE_SAVED"]
UPDATE_SAVED_CLICKS = _s["UPDATE_SAVED_CLICKS"]
EXPAND_REACTIONS = _s["EXPAND_REACTIONS"]
# Empty = Playwright's Chromium, falling back to an installed Chrome, then Edge
BROWSER_CHANNEL = _s["BROWSER_CHANNEL"].lower()
HEADLESS = _s["HEADLESS"]
ANONYMIZE = _s["ANONYMIZE"]

# Kept in .env only: it's a secret, and changing it breaks matching old hashes
HASH_SALT = os.getenv("HASH_SALT", "change-me")

# 127.0.0.1 = only this computer can open the dashboard. Docker needs 0.0.0.0.
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 8765))
