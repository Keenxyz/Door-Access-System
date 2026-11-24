"""Protect access to the local enrollment script with a password verifier."""

import hashlib
import hmac
import json
import os
import warnings
from getpass import GetPassWarning, getpass
from secrets import token_bytes


def password_hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


def require_enrollment_password(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            try:
                saved = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                print("Set a separate enrollment password of at least 12 characters.")
                password = getpass("New enrollment password: ")
                if len(password) < 12 or not password.strip():
                    print("Use at least 12 characters.")
                    return False
                if password != getpass("Confirm enrollment password: "):
                    print("The passwords did not match.")
                    return False
                salt = token_bytes(16)
                verifier = {"salt": salt.hex(), "hash": password_hash(password, salt).hex()}
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    json.dump(verifier, file)
                print("Enrollment password set.")
                return True

            verifier = json.loads(saved)
            salt = bytes.fromhex(verifier["salt"])
            stored_hash = bytes.fromhex(verifier["hash"])
            if len(salt) != 16 or len(stored_hash) != 64:
                raise ValueError("Invalid enrollment password verifier.")
            if hmac.compare_digest(password_hash(getpass("Enrollment password: "), salt), stored_hash):
                return True
            print("Incorrect enrollment password.")
    except FileExistsError:
        print("An enrollment password was just set. Run enrollment again to sign in.")
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("\nOpen an interactive terminal to enter the enrollment password.")
    except (OSError, ValueError, KeyError, TypeError):
        print("Could not read or save the enrollment password verifier.")
    return False
