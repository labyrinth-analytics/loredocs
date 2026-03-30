"""Tests for SQL Optimizer engine (optimizer.py).

Tests the prompt builder and response parsing without calling the real Claude API.
The actual Claude calls are mocked since we cannot make API requests in tests.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# anthropic may not be installed in the test environment; mock it before import
try:
    import anthropic
except ImportError:
    sys.modules["anthropic"] = MagicMock()

from optimizer import _build_user_prompt, SQLOptimizer, SYSTEM_PROMPT


class TestBuildUserPrompt(unittest.TestCase):
    """Test the _build_user_prompt helper."""

    def test_basic_prompt_with_dialect(self):
        result = _build_user_prompt("SELECT * FROM users", "tsql")
        self.assertIn("Dialect: tsql", result)
        self.assertIn("SELECT * FROM users", result)

    def test_prompt_includes_engine(self):
        result = _build_user_prompt("SELECT 1", "postgresql", database_engine="PostgreSQL 16")
        self.assertIn("Engine: PostgreSQL 16", result)

    def test_prompt_includes_table_info(self):
        schema = "CREATE TABLE users (id INT, name VARCHAR(100))"
        result = _build_user_prompt("SELECT * FROM users", "tsql", table_info=schema)
        self.assertIn("Schema context:", result)
        self.assertIn(schema, result)

    def test_prompt_minimal(self):
        result = _build_user_prompt("SELECT 1", "sqlite")
        self.assertIn("Dialect: sqlite", result)
        self.assertIn("Query to optimize:", result)
        self.assertNotIn("Engine:", result)
        self.assertNotIn("Schema context:", result)

    def test_prompt_all_fields(self):
        result = _build_user_prompt(
            "SELECT * FROM orders WHERE status = 'open'",
            "mysql",
            table_info="CREATE TABLE orders (id INT PRIMARY KEY, status VARCHAR(20))",
            database_engine="MySQL 8.0",
        )
        self.assertIn("Dialect: mysql", result)
        self.assertIn("Engine: MySQL 8.0", result)
        self.assertIn("Schema context:", result)
        self.assertIn("Query to optimize:", result)


class TestSystemPrompt(unittest.TestCase):
    """Verify SYSTEM_PROMPT is well-formed."""

    def test_system_prompt_is_ascii_only(self):
        for i, ch in enumerate(SYSTEM_PROMPT):
            self.assertLess(
                ord(ch), 128,
                f"Non-ASCII character at position {i}: {ch!r}",
            )

    def test_system_prompt_mentions_json(self):
        self.assertIn("JSON", SYSTEM_PROMPT)

    def test_system_prompt_mentions_all_dialects(self):
        for dialect in ["SQL Server", "MySQL", "PostgreSQL", "SQLite"]:
            self.assertIn(dialect, SYSTEM_PROMPT)


class TestSQLOptimizerInit(unittest.TestCase):
    """Test SQLOptimizer initialization edge cases."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_empty_api_key_sets_client_none(self):
        with patch("optimizer.anthropic") as mock_anthropic:
            opt = SQLOptimizer()
            # Empty string is falsy, so client should be None
            self.assertIsNone(opt.client)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}, clear=False)
    def test_valid_key_creates_client(self):
        with patch("optimizer.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = MagicMock()
            opt = SQLOptimizer()
            self.assertIsNotNone(opt.client)

    @patch.dict(os.environ, {"OPTIMIZER_MODEL": "claude-haiku-4-5-20251001"}, clear=False)
    def test_custom_model_from_env(self):
        with patch("optimizer.anthropic") as mock_anthropic:
            opt = SQLOptimizer()
            self.assertEqual(opt.model, "claude-haiku-4-5-20251001")

    def test_default_model_is_sonnet(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove OPTIMIZER_MODEL if it exists
            os.environ.pop("OPTIMIZER_MODEL", None)
            with patch("optimizer.anthropic") as mock_anthropic:
                opt = SQLOptimizer()
                self.assertEqual(opt.model, "claude-sonnet-4-6")


class TestSQLOptimizerOptimize(unittest.TestCase):
    """Test the optimize method with mocked Claude responses."""

    def _make_optimizer(self):
        with patch("optimizer.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
                opt = SQLOptimizer()
            return opt, mock_client

    def test_no_client_raises_runtime_error(self):
        import asyncio
        with patch("optimizer.anthropic"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ANTHROPIC_API_KEY", None)
                opt = SQLOptimizer()
        with self.assertRaises(RuntimeError):
            asyncio.get_event_loop().run_until_complete(
                opt.optimize("SELECT 1")
            )

    def test_valid_json_response_parsed(self):
        import asyncio
        opt, mock_client = self._make_optimizer()

        valid_response = {
            "optimized_query": "SELECT id, name FROM users WHERE active = 1",
            "changes": [{"description": "replaced SELECT *", "reason": "efficiency", "impact": "medium"}],
            "index_recommendations": [],
            "execution_analysis": {
                "bottlenecks": ["table scan"],
                "estimated_improvement": "2x faster",
                "notes": "Add index on active column",
            },
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(valid_response))]
        mock_client.messages.create.return_value = mock_msg

        result = asyncio.get_event_loop().run_until_complete(
            opt.optimize("SELECT * FROM users WHERE active = 1", dialect="tsql")
        )
        self.assertEqual(result["optimized_query"], valid_response["optimized_query"])
        self.assertEqual(len(result["changes"]), 1)

    def test_markdown_fenced_json_handled(self):
        import asyncio
        opt, mock_client = self._make_optimizer()

        valid_response = {
            "optimized_query": "SELECT 1",
            "changes": [],
            "index_recommendations": [],
            "execution_analysis": {"bottlenecks": [], "estimated_improvement": "none", "notes": ""},
        }
        fenced = "```json\n" + json.dumps(valid_response) + "\n```"
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=fenced)]
        mock_client.messages.create.return_value = mock_msg

        result = asyncio.get_event_loop().run_until_complete(
            opt.optimize("SELECT 1")
        )
        self.assertEqual(result["optimized_query"], "SELECT 1")

    def test_missing_keys_raises_value_error(self):
        import asyncio
        opt, mock_client = self._make_optimizer()

        # Missing 'execution_analysis'
        incomplete = {
            "optimized_query": "SELECT 1",
            "changes": [],
            "index_recommendations": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(incomplete))]
        mock_client.messages.create.return_value = mock_msg

        with self.assertRaises(ValueError) as ctx:
            asyncio.get_event_loop().run_until_complete(opt.optimize("SELECT 1"))
        self.assertIn("missing required fields", str(ctx.exception).lower())

    def test_invalid_json_raises_value_error(self):
        import asyncio
        opt, mock_client = self._make_optimizer()

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="This is not JSON at all")]
        mock_client.messages.create.return_value = mock_msg

        with self.assertRaises(ValueError):
            asyncio.get_event_loop().run_until_complete(opt.optimize("SELECT 1"))


if __name__ == "__main__":
    unittest.main()
