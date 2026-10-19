"""End to end: the real scraper, a real (headless) Chromium, fake feed pages.

Each scenario runs the scraper in a separate Python process with its own data
folder, like a normal run from the dashboard. Skipped if Playwright's Chromium
isn't installed (python -m playwright install chromium).
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401
from tests.mock_feed import write_feed

ROOT = Path(__file__).resolve().parent.parent


def chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(chromium_available(), "Playwright Chromium not installed")
class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="fbscraper-e2e-"))
        self.env = dict(os.environ, DATA_DIR=str(self.data), PYTHONIOENCODING="utf-8")
        self.feed_a = write_feed(self.data, "group_a", count=30, base_id=5000, group="a")
        self.feed_b = write_feed(self.data, "group_b", count=12, base_id=7000, group="b")
        # An empty session is enough for local pages
        self.python("from secret_store import save_session; save_session({'cookies': [], 'origins': []})")

    def python(self, code):
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        return result.stdout

    def scrape(self, settings, overrides=None):
        base = {"GROUPS": [self.feed_a], "HEADLESS": True, "MIN_DELAY": 1, "MAX_DELAY": 1.2,
                "MAX_IDLE_SCROLLS": 3, "MAX_COMMENTS_PER_POST": 3, "EXPAND_REACTIONS": False,
                "RECYCLE_MB": 0, "BROWSER_CHANNEL": "chromium"}
        (self.data / "settings.json").write_text(json.dumps({**base, **settings}), encoding="utf-8")
        patch = "".join(f"scraper.{k} = {v!r}\n" for k, v in (overrides or {}).items())
        self.python("import scraper\n" + patch + "scraper.scrape_posts()")
        return json.loads((self.data / "status.json").read_text(encoding="utf-8"))

    def files(self, slug):
        return self.data / "groups" / slug

    def test_posts_comments_reactions_and_counts(self):
        status = self.scrape({"MAX_POSTS": 8})
        self.assertEqual(status["state"], "done", status["message"])
        posts = rows(self.files("group_a") / "posts.csv")
        self.assertEqual(len(posts), 8)
        self.assertEqual(len({p["post_id"] for p in posts}), 8)
        for p in posts:
            self.assertIn("đầy đủ", p["text"])           # "Xem thêm" was expanded
            self.assertNotIn("Ẩn bớt", p["text"])       # ...and its label not saved
            self.assertTrue(p["author"].startswith("user_"))  # names hashed

        comments = rows(self.files("group_a") / "comments.csv")
        per_post = {}
        for c in comments:
            per_post.setdefault(c["post_id"], []).append(c)
            self.assertNotIn("REPLY", c["text"])
        self.assertTrue(all(len(v) == 3 for v in per_post.values()))  # limit 3, after "Xem thêm bình luận"

        for r in rows(self.files("group_a") / "reactions.csv"):
            i = int(r["post_id"]) - 5000
            self.assertEqual(int(r["total"]), 10 + i)
            self.assertEqual(int(r["like"]), 10 + i)
            self.assertEqual(int(r["comment_count"]), 12 + i)   # not the "5 bình luận" inside a comment
            self.assertEqual(int(r["share_count"]), i)

    def test_second_run_skips_saved_posts_and_speeds_past_them(self):
        self.scrape({"MAX_POSTS": 12})
        self.scrape({"MAX_POSTS": 6})
        posts = rows(self.files("group_a") / "posts.csv")
        self.assertEqual(len(posts), 18)
        self.assertEqual(len({p["post_id"] for p in posts}), 18)
        log = (self.data / "logs.txt").read_text(encoding="utf-8")
        self.assertIn("(fast)", log)

    def test_batches_continue_where_they_stopped(self):
        status = self.scrape({"BATCH_MODE": True, "BATCH_POSTS": 4, "BATCH_TOTAL": 8},
                             {"BATCH_REST_MIN": 0.02})
        self.assertEqual(status["state"], "done", status["message"])
        self.assertEqual(len(rows(self.files("group_a") / "posts.csv")), 8)
        log = (self.data / "logs.txt").read_text(encoding="utf-8")
        self.assertIn("=== Batch 2", log)
        batch2 = log.split("=== Batch 2")[1]
        self.assertIn("0 already saved", batch2)  # no scrolling back past batch 1's posts

    def test_each_group_gets_its_own_folder(self):
        status = self.scrape({"GROUPS": [self.feed_a, self.feed_b], "SCRAPE_ALL_GROUPS": True, "MAX_POSTS": 5},
                             {"GROUP_PAUSE_MIN": 0.01})
        self.assertEqual(status["state"], "done", status["message"])
        a = {p["post_id"] for p in rows(self.files("group_a") / "posts.csv")}
        b = {p["post_id"] for p in rows(self.files("group_b") / "posts.csv")}
        self.assertEqual((len(a), len(b)), (5, 5))
        self.assertFalse(a & b)


if __name__ == "__main__":
    unittest.main()
