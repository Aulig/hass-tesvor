"""Tesvor Home authentication payload helpers."""

import hashlib
from typing import Any


def hash_password(password: str, encrypt_type: int) -> str:
    """Hash a password using the scheme requested by the account API."""
    algorithm = "sha256" if encrypt_type == 2 else "md5"
    return hashlib.new(algorithm, password.encode()).hexdigest()


def build_login_payload(
    *,
    login_name: str,
    password: str,
    encrypt_type: int,
    phone_code: str,
    country: str,
    source: str,
    registration_id: str,
    app_version: str,
    test_flag: bool,
) -> dict[str, Any]:
    """Build the password-login payload used by Tesvor Home for Android."""
    return {
        "loginName": login_name,
        "password": hash_password(password, encrypt_type),
        "globalRoaming": phone_code,
        "source": source,
        "registrationId": registration_id,
        "countryCode": country,
        "testFlag": test_flag,
        "phoneModel": "Home Assistant",
        "coreVersion": "Home Assistant",
        "appVersion": app_version,
    }
