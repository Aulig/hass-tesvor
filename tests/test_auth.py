"""Tests for Tesvor Home authentication payloads."""

import importlib.util
from pathlib import Path
import unittest


AUTH_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "tesvor"
    / "tesvorhome"
    / "rest"
    / "auth.py"
)
SPEC = importlib.util.spec_from_file_location("tesvor_auth", AUTH_PATH)
AUTH = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUTH)


class TesvorAuthTests(unittest.TestCase):
    """Verify the login behavior extracted from Tesvor Home 1.8.2."""

    def test_current_accounts_use_sha256_and_selected_phone_code(self) -> None:
        """Build an encryptType 2 request with the selected dialing code."""
        payload = AUTH.build_login_payload(
            login_name="person@example.com",
            password="secret",
            encrypt_type=2,
            phone_code="49",
            country="de",
            source="teasvor",
            registration_id="",
            app_version="1.8.2",
            test_flag=False,
        )

        self.assertEqual(
            payload["password"],
            "2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",
        )
        self.assertEqual(payload["globalRoaming"], "49")
        self.assertEqual(payload["countryCode"], "de")
        self.assertEqual(payload["source"], "teasvor")
        self.assertEqual(payload["appVersion"], "1.8.2")
        self.assertIs(payload["testFlag"], False)

    def test_legacy_accounts_use_md5(self) -> None:
        """Keep compatibility with accounts reporting encryptType 1."""
        self.assertEqual(
            AUTH.hash_password("secret", 1),
            "5ebe2294ecd0e0f08eab7690d2a6ee69",
        )


if __name__ == "__main__":
    unittest.main()
