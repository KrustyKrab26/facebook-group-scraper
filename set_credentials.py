"""Store (or remove) your Facebook login in the encrypted vault.

    python set_credentials.py          # save email + password
    python set_credentials.py --clear  # delete the vault (password + session)
"""
import sys
from getpass import getpass

from config import VAULT_FILE
from secret_store import VaultError, delete_vault, save_credentials, vault_exists

if __name__ == "__main__":
    if "--clear" in sys.argv:
        delete_vault()
        print("Deleted the vault (stored password and login session).")
        sys.exit(0)

    if not vault_exists():
        print("Creating a new vault. Pick a passphrase you'll remember;")
        print("it can't be recovered, but you can always --clear and start over.")

    email = input("Facebook email or phone: ").strip()
    password = getpass("Facebook password (hidden): ")
    if not email or not password:
        sys.exit("Nothing saved: email and password are both required.")

    try:
        save_credentials(email, password)
    except VaultError as e:
        sys.exit(str(e))
    print(f"Saved to {VAULT_FILE} (encrypted).")
