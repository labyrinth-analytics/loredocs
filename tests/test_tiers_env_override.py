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
        """Without LOREDOCS_PRO env, get_tier reads from config.json."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOREDOCS_PRO", None)
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_FREE)

    def test_env_set_to_1_returns_pro(self):
        """LOREDOCS_PRO=1 overrides config.json to return pro."""
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1"}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)

    def test_env_set_to_any_value_returns_pro(self):
        """Any non-empty LOREDOCS_PRO value returns pro."""
        with patch.dict(os.environ, {"LOREDOCS_PRO": "yes"}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)

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

    def test_env_overrides_even_when_config_says_pro(self):
        """When config says pro AND env says pro, still returns pro (no conflict)."""
        config_path = self.tmpdir / "config.json"
        config_path.write_text(json.dumps({"tier": "pro"}))
        with patch.dict(os.environ, {"LOREDOCS_PRO": "1"}):
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)

    def test_config_set_to_pro_without_env_returns_pro(self):
        """Config-based pro tier still works when env is not set."""
        config_path = self.tmpdir / "config.json"
        config_path.write_text(json.dumps({"tier": "pro"}))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOREDOCS_PRO", None)
            tier = get_tier(self.tmpdir)
            self.assertEqual(tier, TIER_PRO)


class TestMcpJsonProConfig(unittest.TestCase):
    """Verify .mcp.json files set the correct PRO env vars."""

    def test_loreconvo_plugin_mcp_has_pro_env(self):
        """LoreConvo plugin .mcp.json sets LORECONVO_PRO=1."""
        mcp_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "loreconvo-plugin", ".mcp.json"
        )
        if not os.path.exists(mcp_path):
            self.skipTest("loreconvo-plugin .mcp.json not found")
        with open(mcp_path) as f:
            data = json.load(f)
        env = data["mcpServers"]["loreconvo"]["env"]
        self.assertEqual(env.get("LORECONVO_PRO"), "1")

    def test_loredocs_plugin_mcp_has_pro_env(self):
        """LoreDocs plugin .mcp.json sets LOREDOCS_PRO=1."""
        mcp_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "loredocs-plugin", ".mcp.json"
        )
        if not os.path.exists(mcp_path):
            self.skipTest("loredocs-plugin .mcp.json not found")
        with open(mcp_path) as f:
            data = json.load(f)
        env = data["mcpServers"]["loredocs"]["env"]
        self.assertEqual(env.get("LOREDOCS_PRO"), "1")

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
