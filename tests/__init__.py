"""Tests run against a throwaway data folder and fake feed pages; nothing
here touches Facebook or your real data/ folder.

    python -m unittest discover -s tests -v
"""
import os
import tempfile

# Must happen before any project module is imported: config.py reads these
# once, and a developer's own .env doesn't override values already set here.
_TMP = tempfile.mkdtemp(prefix="fbscraper-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ["SCRAPER_PASSPHRASE"] = "test-passphrase-123"
os.environ["HASH_SALT"] = "test-salt"
os.environ["BROWSER_CHANNEL"] = "chromium"
