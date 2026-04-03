"""Tests for LoreDocs tiers.py LOREDOCS_PRO environment variable override.

Validates the new env-var-driven Pro tier activation added in the
2026-04-02 commit (mirroring the LORECONVO_PRO pattern).

MEG QA -- 2026-04-02
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import the tiers module
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loredocs"))
from tiers import get_tier, set_tier, TIER_FREE, TIER_PRO


class TestLoredocsProEnvOverride(unittest.TestCase):
    """Test LOREDOCS_PRO environment variable overrides config.json tier."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # Write a config.json that says free tier
        config_path = self.tmpdir / "config.json"
        config_path.write_text(json.dumps({"tier": "free"}))

    def test_env_not_set_returns_config_tier(self):
        """Without LOREDOCS_PRO or LAB_DEV_MODE, get_tier reads from config.json."""
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        with patch.dict(os.environ, env, clear=True):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_set_to_1_alone_does_not_return_pro(self):
        """LOREDOCS_PRO=1 alone no longer returns pro -- requires a license key."""
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        env["LOREDOCS_PRO"] = "1"
        with patch.dict(os.environ, env, clear=True):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_dev_bypass_returns_pro(self):
        """LOREDOCS_PRO=1 + LAB_DEV_MODE=1 returns pro (internal agent dev bypass)."""
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1", "LAB_DEV_MODE": "1"}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)

    def test_env_set_to_invalid_value_returns_free(self):
        """A non-key arbitrary value for LOREDOCS_PRO returns free."""
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        env["LOREDOCS_PRO"] = "yes"
        with patch.dict(os.environ, env, clear=True):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_empty_string_returns_free(self):
        """Empty string LOREDOCS_PRO does NOT activate pro."""
        with patch.dict(os.environ, {"LOREDOCS_PRO": ""}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_whitespace_only_returns_free(self):
        """Whitespace-only LOREDOCS_PRO does NOT activate pro (.strip() logic)."""
        with patch.dict(os.environ, {"LOREDOCS_PRO": "   "}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_dev_bypass_with_config_pro(self):
        """Dev bypass + config pro both return pro (no conflict)."""
        config_path = self.tmpdir / "config.json"
        config_path.write_text(json.dumps({"tier": "pro"}))
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1", "LAB_DEV_MODE": "1"}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)

    def test_config_set_to_pro_without_env_returns_pro(self):
        """Config-based pro tier still works when neither env var is set."""
        config_path = self.tmpdir / "config.json"
        config_path.write_text(json.dumps({"tier": "pro"}))
        env = {k: v for k, v in os.environ.items() if k not in ("LOREDOCS_PRO", "LAB_DEV_MODE")}
        with patch.dict(os.environ, env, clear=True):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)


class TestMcpJsonProConfig(unittest.TestCase):
    """Verify .mcp.json files set the correct PRO env vars."""

    def test_loreconvo_plugin_mcp_has_free_tier_default(self):
        """LoreConvo PUBLIC plugin .mcp.json must default to free tier (LORECONVO_PRO='')."""
        mcp_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "loreconvo-plugin", ".mcp.json"
        )
        if not os.path.exists(mcp_path):
            self.skipTest("loreconvo-plugin .mcp.json not found")
        with open(mcp_path) as f:
            data = json.load(f)
        env = data["mcpServers"]["loreconvo"]["env"]
        self.assertEqual(env.get("LORECONVO_PRO"), "")

    def test_loredocs_plugin_mcp_has_free_tier_default(self):
        """LoreDocs PUBLIC plugin .mcp.json must default to free tier (LOREDOCS_PRO='')."""
        mcp_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "loredocs-plugin", ".mcp.json"
        )
        if not os.path.exists(mcp_path):
            self.skipTest("loredocs-plugin .mcp.json not found")
        with open(mcp_path) as f:
            data = json.load(f)
        env = data["mcpServers"]["loredocs"]["env"]
        self.assertEqual(env.get("LOREDOCS_PRO"), "")

    def test_loreconvo_dev_mcp_has_pro_env(self):
        """LoreConvo dev .mcp.json sets LORECONVO_PRO=1."""
        mcp_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "loreconvo", ".mcp.json"
        )
        if not os.path.exists(mcp_path):
            self.skipTest("loreconvo .mcp.json not found")
        with open(mcp_path) as f:
            data = json.load(f)
        env = data["mcpServers"]["loreconvo"]["env"]
        self.assertEqual(env.get("LORECONVO_PRO"), "1")


if __name__ == "__main__":
    unittest.main()
