"""Pure functions: number and date parsing, text cleaning, cookies, settings."""
import unittest

import tests  # noqa: F401  (sets up the test environment first)
from analytics import parse_post_time
from config import group_slug, validate_settings
from import_session import from_fields, parse_text, session_from_cookies
from reactions import build_row, footer_values, merge_row, parse_count, parse_total
from utils import clean_text

BASE = "2026-10-17T15:00:00"


class Counts(unittest.TestCase):
    def test_parse_count(self):
        cases = {"1,2K": 1200, "1.2K": 1200, "2,5 N": 2500, "1 Tr": 1_000_000, "1.234": 1234,
                 "1,234": 1234, "45 người": 45, "Thích: 120 người": 120, "12": 12, "": None}
        for text, want in cases.items():
            self.assertEqual(parse_count(text), want, text)

    def test_parse_total(self):
        cases = {"128": 128, "Bạn và 45 người khác": 46, "Bạn, An và 45 người khác": 47,
                 "You and 1.2K others": 1201}
        for text, want in cases.items():
            self.assertEqual(parse_total(text), want, text)

    def test_footer_values(self):
        self.assertEqual(footer_values({"comments": "48", "shares": "", "footer": True}),
                         {"comment_count": 48, "share_count": 0})
        self.assertEqual(footer_values({}), {"comment_count": "", "share_count": ""})

    def test_merge_keeps_types_a_bar_reading_cant_see(self):
        old = build_row("1", {"found": {"like": "80", "love": "15", "wow": "1"}, "totalText": "96"}, None, "t0")
        new = build_row("1", {"found": {"like": "100", "love": "20"}, "totalText": "130"}, None, "t1",
                        {"comments": "9", "footer": True})
        row, changed = merge_row(old, new, "t1")
        self.assertTrue(changed)
        self.assertEqual((row["like"], row["love"], row["wow"], row["total"]), (100, 20, 1, 130))
        self.assertEqual(row["comment_count"], 9)


class Text(unittest.TestCase):
    def test_button_labels_removed(self):
        self.assertEqual(clean_text("Keybox Kafe \n Ẩn bớt"), "Keybox Kafe")
        self.assertEqual(clean_text("Văn bằng c… Xem thêm"), "Văn bằng c…")
        self.assertEqual(clean_text("Bài dài\nXem thêm\nđoạn sau"), "Bài dài\nđoạn sau")

    def test_normal_sentences_kept(self):
        for text in ("Muốn biết chi tiết thì xem thêm", "See more of this on our page"):
            self.assertEqual(clean_text(text), text)


class PostTime(unittest.TestCase):
    def test_formats(self):
        cases = {
            "2 giờ": ("2026-10-17T13:00", True),
            "45 phút": ("2026-10-17T14:15", True),
            "3 ngày": ("2026-10-14T15:00", False),
            "Hôm qua lúc 14:30": ("2026-10-16T14:30", True),
            "Yesterday at 2:30 PM": ("2026-10-16T14:30", True),
            "12 tháng 10 lúc 08:15": ("2026-10-12T08:15", True),
            "October 12 at 9:05 AM": ("2026-10-12T09:05", True),
            "25 tháng 12": ("2025-12-25T00:00", False),
        }
        for text, (when, has_time) in cases.items():
            got, got_time = parse_post_time(text, BASE)
            self.assertEqual((got.isoformat(timespec="minutes"), got_time), (when, has_time), text)
        self.assertEqual(parse_post_time("abc", BASE), (None, False))


class Cookies(unittest.TestCase):
    def test_formats(self):
        for text in ("c_user=100012345; xs=12%3Aabc; datr=zz",
                     '[{"domain":".facebook.com","name":"c_user","value":"9"},'
                     '{"domain":".facebook.com","name":"xs","value":"q"}]',
                     ".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t77\n#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\txs\tw"):
            names = {c["name"] for c in session_from_cookies(parse_text(text))["cookies"]}
            self.assertTrue({"c_user", "xs"} <= names, text)

    def test_rejects_incomplete_or_wrong(self):
        with self.assertRaises(ValueError):
            session_from_cookies(from_fields({"c_user": "123"}))
        with self.assertRaises(ValueError):
            session_from_cookies(from_fields({"c_user": "Nguyen", "xs": "a"}))

    def test_other_sites_dropped(self):
        cookies = parse_text('[{"domain":".facebook.com","name":"c_user","value":"1"},'
                             '{"domain":".facebook.com","name":"xs","value":"2"},'
                             '{"domain":".google.com","name":"SID","value":"x"}]')
        self.assertEqual(len(session_from_cookies(cookies)["cookies"]), 2)


class Settings(unittest.TestCase):
    def test_group_list(self):
        ok, errors = validate_settings({"GROUPS": "https://www.facebook.com/groups/a\nhttps://www.facebook.com/groups/b/"})
        self.assertEqual(errors, {})
        self.assertEqual(ok["GROUPS"], ["https://www.facebook.com/groups/a", "https://www.facebook.com/groups/b"])
        self.assertIn("GROUPS", validate_settings({"GROUPS": "https://example.com/x"})[1])
        self.assertIn("GROUPS", validate_settings({"GROUPS": ["https://www.facebook.com/groups/a",
                                                             "https://m.facebook.com/groups/a"]})[1])

    def test_ranges(self):
        self.assertIn("MAX_POSTS", validate_settings({"MAX_POSTS": 9999})[1])
        self.assertIn("MAX_DELAY", validate_settings({"MIN_DELAY": 10, "MAX_DELAY": 5})[1])

    def test_group_slug(self):
        self.assertEqual(group_slug("https://www.facebook.com/groups/some.group-name"), "some.group-name")
        self.assertEqual(group_slug("file:///tmp/feed_one.html"), "feed_one")


if __name__ == "__main__":
    unittest.main()
