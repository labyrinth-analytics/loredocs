"""
Tests for the credit management system.
Run with: python -m pytest tests/ -v
"""

import os
import json
import tempfile
import pytest
from pathlib import Path

# Override DATA_DIR before importing credits module
_test_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _test_dir

from credits import CreditManager


@pytest.fixture
def manager():
    """Fresh CreditManager with a clean data directory for each test."""
    test_dir = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = test_dir
    # Re-initialize with new path
    mgr = CreditManager()
    return mgr


class TestKeyGeneration:
    def test_generate_key_returns_prefixed_string(self, manager):
        key = manager.generate_key(plan="starter", credits=50)
        assert key.startswith("ron_sk_")
        assert len(key) > 20

    def test_generated_key_is_valid(self, manager):
        key = manager.generate_key()
        assert manager.is_valid_key(key) is True

    def test_random_key_is_invalid(self, manager):
        assert manager.is_valid_key("ron_sk_fake_key_12345") is False

    def test_keys_are_unique(self, manager):
        key1 = manager.generate_key()
        key2 = manager.generate_key()
        assert key1 != key2


class TestCreditOperations:
    def test_starter_gets_correct_credits(self, manager):
        key = manager.generate_key(plan="starter", credits=50)
        assert manager.get_credits(key) == 50

    def test_pro_gets_correct_credits(self, manager):
        key = manager.generate_key(plan="pro", credits=200)
        assert manager.get_credits(key) == 200

    def test_use_credit_decrements(self, manager):
        key = manager.generate_key(plan="starter", credits=5)
        assert manager.get_credits(key) == 5

        manager.use_credit(key)
        assert manager.get_credits(key) == 4

    def test_use_credit_fails_at_zero(self, manager):
        key = manager.generate_key(plan="starter", credits=1)
        assert manager.use_credit(key) is True
        assert manager.get_credits(key) == 0
        assert manager.use_credit(key) is False

    def test_add_credits(self, manager):
        key = manager.generate_key(plan="starter", credits=10)
        manager.add_credits(key, 50)
        assert manager.get_credits(key) == 60

    def test_unlimited_plan_never_decrements(self, manager):
        key = manager.generate_key(plan="unlimited", credits=0)
        initial = manager.get_credits(key)

        for _ in range(10):
            assert manager.use_credit(key) is True

        # Credits should not decrease for unlimited
        assert manager.get_credits(key) == initial


class TestPlanInfo:
    def test_get_plan(self, manager):
        key = manager.generate_key(plan="pro", credits=200)
        assert manager.get_plan(key) == "pro"

    def test_invalid_key_returns_unknown(self, manager):
        assert manager.get_plan("ron_sk_nonexistent") == "unknown"


class TestKeyHashing:
    def test_raw_keys_not_stored(self, manager):
        key = manager.generate_key()
        # Read the raw JSON file from the manager's actual data location
        from credits import CREDITS_FILE
        raw_data = CREDITS_FILE.read_text()
        # The raw key should NOT appear in the file
        assert key not in raw_data
        # But the hash should
        assert manager._hash_key(key) in raw_data
