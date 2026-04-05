"""Tests for vault_set_tier license gate (GINA-001 / SEC-017 fix).

Verifies that vault_set_tier rejects Pro upgrade attempts when no valid
license is present, and allows upgrades when a valid license is active.
Also verifies that downgrade to free does not require a license.

vault_set_tier is an async MCP tool (params, ctx). Tests call it via
asyncio.run() with a MagicMock for ctx. For rejection cases (no valid
license) the ctx is never accessed because the function returns early.
For success cases, set_tier and _get_storage are mocked out.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path

# Add the loredocs package to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loredocs.server import vault_set_tier, VaultSetTierInput


def _make_params(tier):
    return VaultSetTierInput(tier=tier)


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _mock_ctx():
    """Return a MagicMock suitable for the ctx parameter."""
    return MagicMock()


class TestVaultSetTierLicenseGate(unittest.TestCase):
    """vault_set_tier must reject Pro upgrade when no valid license is active."""

    def test_upgrade_to_pro_without_license_returns_error(self):
        """No LOREDOCS_PRO env var => upgrade to pro is rejected."""
        free_status = {"is_pro": False, "mode": "free"}
        with patch("loredocs.server.get_license_status", return_value=free_status):
            result = _run(vault_set_tier(_make_params("pro"), _mock_ctx()))
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("Error"), f"Expected error, got: {result}")
        self.assertIn("license", result.lower())

    def test_upgrade_to_pro_with_invalid_key_returns_error(self):
        """Invalid LOREDOCS_PRO key => upgrade to pro is rejected with specific message."""
        invalid_status = {
            "is_pro": False,
            "mode": "invalid_key",
            "error": "Signature verification failed",
        }
        with patch("loredocs.server.get_license_status", return_value=invalid_status):
            result = _run(vault_set_tier(_make_params("pro"), _mock_ctx()))
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("Error"), f"Expected error, got: {result}")
        self.assertIn("Invalid", result)

    def test_upgrade_to_pro_with_valid_license_succeeds(self):
        """Valid license key => upgrade to pro is allowed."""
        valid_status = {"is_pro": True, "mode": "licensed"}
        mock_ctx = _mock_ctx()
        with patch("loredocs.server.get_license_status", return_value=valid_status):
            with patch("loredocs.server.set_tier") as mock_set:
                with patch("loredocs.server._get_storage"):
                    result = _run(vault_set_tier(_make_params("pro"), mock_ctx))
        mock_set.assert_called_once()
        self.assertFalse(
            str(result).startswith("Error"),
            f"Expected success but got error: {result}",
        )

    def test_upgrade_to_pro_with_dev_bypass_succeeds(self):
        """Dev bypass mode => upgrade to pro is allowed."""
        dev_status = {"is_pro": True, "mode": "dev_bypass"}
        with patch("loredocs.server.get_license_status", return_value=dev_status):
            with patch("loredocs.server.set_tier"):
                with patch("loredocs.server._get_storage"):
                    result = _run(vault_set_tier(_make_params("pro"), _mock_ctx()))
        self.assertFalse(
            str(result).startswith("Error"),
            f"Expected success but got error: {result}",
        )

    def test_downgrade_to_free_does_not_require_license(self):
        """Downgrading to free tier never calls get_license_status."""
        with patch("loredocs.server.get_license_status") as mock_status:
            with patch("loredocs.server.set_tier"):
                with patch("loredocs.server._get_storage"):
                    _run(vault_set_tier(_make_params("free"), _mock_ctx()))
        mock_status.assert_not_called()

    def test_invalid_tier_value_is_rejected(self):
        """Passing an unsupported tier value is rejected by Pydantic validation."""
        with self.assertRaises(Exception):
            _make_params("enterprise")

    def test_error_message_includes_actionable_instructions(self):
        """Error message for missing license should tell user what to do."""
        free_status = {"is_pro": False, "mode": "free"}
        with patch("loredocs.server.get_license_status", return_value=free_status):
            result = _run(vault_set_tier(_make_params("pro"), _mock_ctx()))
        # Should mention the env var users need to set
        self.assertIn("LOREDOCS_PRO", result)


if __name__ == "__main__":
    unittest.main()
