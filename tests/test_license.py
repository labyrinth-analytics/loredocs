"""
Tests for LoreDocs license key validation (loredocs/license.py).

Uses a dedicated TEST keypair -- the production signing key is never embedded
in source or tests. Tests patch the module-level public key constant so they
are completely isolated from production keys.
"""

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Test keypair (generated for tests only -- NOT the production signing key)
# ---------------------------------------------------------------------------

TEST_PUBLIC_KEY_B64 = "nTuyInWLiA0jY37WsOziSY41NfWplU5BDNiKGW4tjmU="

LD_KEY = (
    "LAB-eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOiIyMDk5LTAxLTAxIiwi"
    "aXNzIjoiMS4wIiwicHJvZHVjdCI6ImxvcmVkb2NzIiwidGllciI6InBybyJ9.ezyOm0OD"
    "A4eC1YwSmXfifltCFIf2mlO6hhZdtsUDGeaH6xIQtHf5Qd-Poe6ewN3wwCq6XFcN4Q_H"
    "aOFqoE-9Cg"
)
SUITE_KEY = (
    "LAB-eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOiIyMDk5LTAxLTAxIiwi"
    "aXNzIjoiMS4wIiwicHJvZHVjdCI6ImxvcmVfc3VpdGUiLCJ0aWVyIjoicHJvIn0.uSHq4"
    "BIx80u_Ai6kfs2alrlgrMpz0XoVyjOV7vkrROQQD_oVJkPHE7o0WCFiloJFs6z6gtaQFv"
    "Cb9N0PjVWEBQ"
)
EXPIRED_KEY = (
    "LAB-eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOiIyMDIwLTAxLTAxIiwi"
    "aXNzIjoiMS4wIiwicHJvZHVjdCI6ImxvcmVjb252byIsInRpZXIiOiJwcm8ifQ.-5oYjz"
    "Z5aPx66h5Ws3h1FC2FKQ36m8RPPwd8Q_6HvbJLJEYo75kp91lhVrpQHxeCUKxrG-qmIc4"
    "7aANUt6CAAA"
)
LORECONVO_KEY = (
    "LAB-eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOiIyMDk5LTAxLTAxIiwi"
    "aXNzIjoiMS4wIiwicHJvZHVjdCI6ImxvcmVjb252byIsInRpZXIiOiJwcm8ifQ.UP9r6D"
    "qf0J9D3ZIl7wunUHhzb27HNCily236UL4bCSKE8-uSvae7M2VTOuU6nEBCcx1L_0w_rrF"
    "TPB84KW8oDg"
)


def _patch_pubkey():
    import loredocs.license as lic_mod
    return patch.object(lic_mod, "_LAB_PUBLIC_KEY_B64", TEST_PUBLIC_KEY_B64)


class TestValidateLicenseKeyLoreDocs(unittest.TestCase):
    """validate_license_key() for LoreDocs."""

    def test_valid_loredocs_key(self):
        from loredocs.license import validate_license_key
        with _patch_pubkey():
            payload = validate_license_key(LD_KEY)
        self.assertEqual(payload["product"], "loredocs")
        self.assertEqual(payload["tier"], "pro")

    def test_valid_lore_suite_key(self):
        from loredocs.license import validate_license_key
        with _patch_pubkey():
            payload = validate_license_key(SUITE_KEY)
        self.assertEqual(payload["product"], "lore_suite")

    def test_expired_key_raises(self):
        # EXPIRED_KEY is a loreconvo key -- LoreDocs rejects it for wrong product.
        # The important thing is that it raises LicenseError (not silently grants Pro).
        from loredocs.license import validate_license_key, LicenseError
        with _patch_pubkey():
            with self.assertRaises(LicenseError):
                validate_license_key(EXPIRED_KEY)

    def test_loreconvo_key_rejected_by_loredocs(self):
        """A loreconvo-specific key must not work for loredocs."""
        from loredocs.license import validate_license_key, LicenseError
        with _patch_pubkey():
            with self.assertRaises(LicenseError) as ctx:
                validate_license_key(LORECONVO_KEY)
        self.assertIn("loreconvo", str(ctx.exception))

    def test_tampered_key_raises(self):
        from loredocs.license import validate_license_key, LicenseError
        parts = LD_KEY[4:].split(".")
        bad_sig = base64.urlsafe_b64encode(b"z" * 64).rstrip(b"=").decode()
        with _patch_pubkey():
            with self.assertRaises(LicenseError):
                validate_license_key(f"LAB-{parts[0]}.{bad_sig}")

    def test_no_prefix_raises(self):
        from loredocs.license import validate_license_key, LicenseError
        with _patch_pubkey():
            with self.assertRaises(LicenseError):
                validate_license_key("notakey")


class TestIsProLicensedLoreDocs(unittest.TestCase):
    """is_pro_licensed() for LoreDocs."""

    def test_empty_env_is_free(self):
        from loredocs.license import is_pro_licensed
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(is_pro_licensed())

    def test_valid_key_is_pro(self):
        from loredocs.license import is_pro_licensed
        with _patch_pubkey():
            with patch.dict(os.environ, {"LOREDOCS_PRO": LD_KEY, "LAB_DEV_MODE": ""}, clear=False):
                self.assertTrue(is_pro_licensed())

    def test_dev_bypass_both_flags(self):
        from loredocs.license import is_pro_licensed
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1", "LAB_DEV_MODE": "1"}, clear=False):
            self.assertTrue(is_pro_licensed())

    def test_old_env_var_alone_is_free(self):
        """LOREDOCS_PRO=1 alone must NOT grant Pro after the license update."""
        from loredocs.license import is_pro_licensed
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        env["LOREDOCS_PRO"] = "1"
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(is_pro_licensed())

    def test_suite_key_is_pro(self):
        from loredocs.license import is_pro_licensed
        with _patch_pubkey():
            with patch.dict(os.environ, {"LOREDOCS_PRO": SUITE_KEY, "LAB_DEV_MODE": ""}, clear=False):
                self.assertTrue(is_pro_licensed())


class TestGetTierIntegration(unittest.TestCase):
    """get_tier() in tiers.py uses license.is_pro_licensed()."""

    def _make_root(self):
        tmp = tempfile.mkdtemp()
        return Path(tmp)

    def test_env_key_grants_pro_tier(self):
        from loredocs.tiers import get_tier, TIER_PRO
        root = self._make_root()
        with _patch_pubkey():
            with patch.dict(os.environ, {"LOREDOCS_PRO": LD_KEY, "LAB_DEV_MODE": ""}, clear=False):
                tier = get_tier(root)
        self.assertEqual(tier, TIER_PRO)

    def test_invalid_env_falls_to_free_tier(self):
        from loredocs.tiers import get_tier, TIER_FREE
        root = self._make_root()
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        env["LOREDOCS_PRO"] = "not-a-key"
        with _patch_pubkey():
            with patch.dict(os.environ, env, clear=True):
                tier = get_tier(root)
        self.assertEqual(tier, TIER_FREE)

    def test_config_json_fallback_still_works(self):
        """config.json tier='pro' should still work as a fallback for activated users."""
        import json
        from loredocs.tiers import get_tier, TIER_PRO
        root = self._make_root()
        config_path = root / "config.json"
        config_path.write_text(json.dumps({"tier": "pro"}))
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        with patch.dict(os.environ, env, clear=True):
            tier = get_tier(root)
        self.assertEqual(tier, TIER_PRO)

    def test_dev_bypass_grants_pro_tier(self):
        from loredocs.tiers import get_tier, TIER_PRO
        root = self._make_root()
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1", "LAB_DEV_MODE": "1"}, clear=False):
            tier = get_tier(root)
        self.assertEqual(tier, TIER_PRO)


if __name__ == "__main__":
    unittest.main()
