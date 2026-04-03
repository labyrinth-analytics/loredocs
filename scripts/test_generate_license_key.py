"""
Tests for scripts/generate_license_key.py

Uses a dedicated TEST keypair -- the production signing key is never
embedded in source or tests.  Tests mock load_private_key() so they
are fully isolated from any production secrets.

Coverage:
  - generate_license_key(): product validation, expiry validation, key format
  - round-trip: generate with test private key, validate with test public key
  - _b64url_encode: roundtrip with _b64url_decode from license modules
"""

import base64
import importlib.util
import json
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load the script as a module (it lives in scripts/, not a package)
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path(__file__).parent / "generate_license_key.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("generate_license_key", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_script = _load_script()
generate_license_key = _script.generate_license_key
_b64url_encode = _script._b64url_encode

# ---------------------------------------------------------------------------
# Test keypair (NOT the production key)
# ---------------------------------------------------------------------------

def _generate_test_keypair():
    """Generate a fresh Ed25519 keypair for testing."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat, PrivateFormat, NoEncryption,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_bytes).decode()
    return private_key, pub_b64


_TEST_PRIVATE_KEY, _TEST_PUBLIC_KEY_B64 = _generate_test_keypair()


def _patch_private_key():
    """Patch load_private_key to return the test private key."""
    return patch.object(_script, "load_private_key", return_value=_TEST_PRIVATE_KEY)


def _patch_validator_pubkey(loreconvo_mod=None, loredocs_mod=None):
    """Return a list of context managers that swap in the test public key."""
    patches = []
    if loreconvo_mod:
        import core.license as lc_lic
        patches.append(patch.object(lc_lic, "_LAB_PUBLIC_KEY_B64", _TEST_PUBLIC_KEY_B64))
    return patches


# ---------------------------------------------------------------------------
# Tests: input validation in generate_license_key()
# ---------------------------------------------------------------------------

class TestGenerateLicenseKeyValidation(unittest.TestCase):

    def test_invalid_product_raises(self):
        with _patch_private_key():
            with self.assertRaises(ValueError) as ctx:
                generate_license_key("notaproduct", "a@b.com", "never")
        self.assertIn("notaproduct", str(ctx.exception))

    def test_valid_products_accepted(self):
        """All three valid product codes must not raise ValueError on product check."""
        for product in ("loreconvo", "loredocs", "lore_suite"):
            with _patch_private_key():
                key = generate_license_key(product, "test@example.com", "never")
            self.assertTrue(key.startswith("LAB-"), f"Key for {product} must start with LAB-")

    def test_past_expiry_raises(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        with _patch_private_key():
            with self.assertRaises(ValueError) as ctx:
                generate_license_key("loreconvo", "a@b.com", past)
        self.assertIn("future", str(ctx.exception).lower())

    def test_today_expiry_raises(self):
        """Expiry must be strictly in the future (not today, since today has passed/is passing)."""
        today = date.today().isoformat()
        with _patch_private_key():
            with self.assertRaises(ValueError):
                generate_license_key("loreconvo", "a@b.com", today)

    def test_invalid_date_format_raises(self):
        with _patch_private_key():
            with self.assertRaises(ValueError) as ctx:
                generate_license_key("loreconvo", "a@b.com", "2099/01/01")
        self.assertIn("2099/01/01", str(ctx.exception))

    def test_never_expiry_does_not_raise(self):
        with _patch_private_key():
            key = generate_license_key("loreconvo", "a@b.com", "never")
        self.assertTrue(key.startswith("LAB-"))

    def test_future_date_expiry_does_not_raise(self):
        future = (date.today() + timedelta(days=365)).isoformat()
        with _patch_private_key():
            key = generate_license_key("loreconvo", "a@b.com", future)
        self.assertTrue(key.startswith("LAB-"))


# ---------------------------------------------------------------------------
# Tests: output format of generate_license_key()
# ---------------------------------------------------------------------------

class TestGenerateLicenseKeyFormat(unittest.TestCase):

    def test_key_starts_with_lab_prefix(self):
        with _patch_private_key():
            key = generate_license_key("loreconvo", "user@x.com", "never")
        self.assertTrue(key.startswith("LAB-"))

    def test_key_has_exactly_two_dot_separated_parts(self):
        with _patch_private_key():
            key = generate_license_key("loreconvo", "user@x.com", "never")
        body = key[4:]   # strip "LAB-"
        parts = body.split(".")
        self.assertEqual(len(parts), 2, "Key body must have exactly one '.' separator")

    def test_key_contains_valid_base64url(self):
        """Both parts of the key should be valid base64url strings."""
        with _patch_private_key():
            key = generate_license_key("loreconvo", "user@x.com", "never")
        body = key[4:]
        encoded_payload, encoded_sig = body.split(".")
        # Should decode without error
        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        self.assertIsInstance(decoded, bytes)

    def test_payload_contains_expected_fields(self):
        """The decoded payload must contain product, tier, exp, iss, email."""
        with _patch_private_key():
            key = generate_license_key("loreconvo", "test@example.com", "2099-01-01")
        body = key[4:]
        encoded_payload = body.split(".")[0]
        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        self.assertEqual(payload["product"], "loreconvo")
        self.assertEqual(payload["tier"], "pro")
        self.assertEqual(payload["exp"], "2099-01-01")
        self.assertEqual(payload["iss"], "1.0")
        self.assertEqual(payload["email"], "test@example.com")

    def test_payload_keys_are_sorted(self):
        """Payload JSON keys must be sorted (ensures deterministic encoding for signature)."""
        with _patch_private_key():
            key = generate_license_key("loreconvo", "a@b.com", "never")
        body = key[4:]
        encoded_payload = body.split(".")[0]
        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload_str = payload_bytes.decode("utf-8")
        # Re-serialize with same settings to verify sorted order
        payload_obj = json.loads(payload_str)
        expected_str = json.dumps(payload_obj, separators=(",", ":"), sort_keys=True)
        self.assertEqual(payload_str, expected_str)

    def test_no_padding_chars_in_key(self):
        """Base64url parts must not contain '=' padding characters."""
        with _patch_private_key():
            key = generate_license_key("loreconvo", "a@b.com", "never")
        self.assertNotIn("=", key, "Key must not contain base64 padding '='")


# ---------------------------------------------------------------------------
# Tests: round-trip generate -> validate
# ---------------------------------------------------------------------------

class TestRoundTrip(unittest.TestCase):
    """Generate with test private key; validate with test public key patched into license module."""

    def _get_loreconvo_path(self):
        return str(Path(__file__).parent.parent / "ron_skills" / "loreconvo" / "src")

    def test_roundtrip_loreconvo(self):
        """Generated LoreConvo key validates correctly with the LoreConvo validator."""
        src_path = self._get_loreconvo_path()
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        import core.license as lc_lic

        with _patch_private_key():
            key = generate_license_key("loreconvo", "alice@example.com", "2099-01-01")

        with patch.object(lc_lic, "_LAB_PUBLIC_KEY_B64", _TEST_PUBLIC_KEY_B64):
            payload = lc_lic.validate_license_key(key)

        self.assertEqual(payload["product"], "loreconvo")
        self.assertEqual(payload["tier"], "pro")
        self.assertEqual(payload["email"], "alice@example.com")

    def test_roundtrip_lore_suite_accepted_by_loreconvo(self):
        """lore_suite keys must be accepted by the LoreConvo validator."""
        src_path = self._get_loreconvo_path()
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        import core.license as lc_lic

        with _patch_private_key():
            key = generate_license_key("lore_suite", "bob@company.com", "never")

        with patch.object(lc_lic, "_LAB_PUBLIC_KEY_B64", _TEST_PUBLIC_KEY_B64):
            payload = lc_lic.validate_license_key(key)

        self.assertEqual(payload["product"], "lore_suite")

    def test_roundtrip_loreconvo_key_rejected_by_production_pubkey(self):
        """Keys signed with the test private key must be rejected by the real production public key."""
        src_path = self._get_loreconvo_path()
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        import core.license as lc_lic

        with _patch_private_key():
            key = generate_license_key("loreconvo", "a@b.com", "never")

        # Do NOT patch the pubkey -- use the real production public key.
        # Since the test key was signed with a different private key, it must be rejected.
        with self.assertRaises(lc_lic.LicenseError):
            lc_lic.validate_license_key(key)


# ---------------------------------------------------------------------------
# Tests: _b64url_encode helper
# ---------------------------------------------------------------------------

class TestB64UrlEncode(unittest.TestCase):

    def test_no_padding(self):
        """Encoded output must never end with '='."""
        for length in range(1, 20):
            encoded = _b64url_encode(b"x" * length)
            self.assertNotIn("=", encoded, f"Padding found for input length {length}")

    def test_ascii_only_output(self):
        """Output must be ASCII-only."""
        encoded = _b64url_encode(b"\xff\xfe\xfd" * 10)
        self.assertTrue(encoded.isascii())

    def test_roundtrip(self):
        """Encoding and decoding must recover the original bytes."""
        for data in (b"", b"a", b"hello world", b"\x00\xff\xde\xad\xbe\xef"):
            encoded = _b64url_encode(data)
            padded = encoded + "=" * (-len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            self.assertEqual(decoded, data)


if __name__ == "__main__":
    unittest.main()
