"""Author names: hashed before saving, and loud warnings when they wouldn't be safe."""
import unittest
from unittest import mock

import tests  # noqa: F401
import utils


class Hashing(unittest.TestCase):
    def test_same_person_same_code_and_no_name_left(self):
        a = utils.anonymize("Nguyễn Văn A")
        self.assertEqual(a, utils.anonymize("Nguyễn Văn A"))
        self.assertNotEqual(a, utils.anonymize("Nguyễn Văn B"))
        self.assertRegex(a, r"^user_[0-9a-f]{12}$")
        self.assertNotIn("Nguyễn", a)

    def test_salt_changes_the_codes(self):
        a = utils.anonymize("Nguyễn Văn A")
        with mock.patch.object(utils, "HASH_SALT", "another-long-salt"):
            self.assertNotEqual(utils.anonymize("Nguyễn Văn A"), a)

    def test_hashing_is_on_by_default(self):
        from config import SCHEMA
        self.assertTrue(SCHEMA["ANONYMIZE"]["default"])


class Warnings(unittest.TestCase):
    def test_fine_with_a_real_salt(self):
        with mock.patch.object(utils, "HASH_SALT", "3f9a1c07b2e4d5f6a7b8"), mock.patch.object(utils, "ANONYMIZE", True):
            self.assertEqual(utils.privacy_warnings(), [])

    def test_placeholder_or_short_salt(self):
        for salt in ("change-me", "pick-any-random-string", "abc"):
            with mock.patch.object(utils, "HASH_SALT", salt), mock.patch.object(utils, "ANONYMIZE", True):
                self.assertTrue(utils.privacy_warnings(), salt)

    def test_hashing_off(self):
        with mock.patch.object(utils, "ANONYMIZE", False):
            self.assertIn("NOT hashed", utils.privacy_warnings()[0])


if __name__ == "__main__":
    unittest.main()
