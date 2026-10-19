"""The encrypted vault: nothing readable on disk, wrong passphrase refused."""
import os
import unittest

import tests  # noqa: F401
import secret_store
from config import VAULT_FILE


class Vault(unittest.TestCase):
    def setUp(self):
        secret_store.delete_vault()
        secret_store._passphrase = None

    def test_round_trip_and_nothing_in_plain_text(self):
        secret_store.save_credentials("someone@example.com", "not-a-real-password")
        secret_store.save_session({"cookies": [{"name": "c_user", "value": "100099998888",
                                                "domain": ".facebook.com", "path": "/"}], "origins": []})
        with open(VAULT_FILE, "rb") as f:
            raw = f.read()
        for secret in (b"someone@example.com", b"not-a-real-password", b"100099998888"):
            self.assertNotIn(secret, raw)
        self.assertEqual(secret_store.get_credentials(), ("someone@example.com", "not-a-real-password"))
        self.assertEqual(secret_store.account_info()["account"], "…8888")

    def test_wrong_passphrase(self):
        secret_store.save_session({"cookies": [], "origins": []})
        secret_store._passphrase = None
        with self.assertRaises(secret_store.VaultError):
            secret_store.set_passphrase("wrong passphrase")

    def test_forget_password_removes_both(self):
        secret_store.save_credentials("someone@example.com", "not-a-real-password")
        secret_store.forget_credentials()
        info = secret_store.account_info()
        self.assertFalse(info["has_saved_password"])
        self.assertEqual(info["saved_email"], "")

    def tearDown(self):
        secret_store.delete_vault()
        secret_store._passphrase = os.environ["SCRAPER_PASSPHRASE"]


if __name__ == "__main__":
    unittest.main()
