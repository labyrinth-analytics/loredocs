"""
Credit Management System
=========================
Handles API key validation, credit tracking, and plan management.

For MVP, this uses a simple JSON file as the datastore.
For production, swap to PostgreSQL or SQLite with the same interface.

Pricing tiers:
  - Starter:   $9.99  / 50 credits   ($0.20 per optimization)
  - Pro:       $29.99 / 200 credits   ($0.15 per optimization)
  - Unlimited: $79.99 / month         (unlimited optimizations)

Our COGS per optimization is ~$0.005-$0.05 (Claude API call).
At $0.15-$0.20 per credit, that is a 3-40x margin.
"""

import os
import json
import hashlib
import secrets
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sql_optimizer_api.credits")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
CREDITS_FILE = DATA_DIR / "credits.json"
UNLIMITED_PLAN_CREDIT_DISPLAY = 999999


class CreditManager:
    """
    Manages API keys and credit balances.

    For MVP: JSON file storage.
    For production: replace _load/_save with database calls.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        """Create the credits file if it does not exist."""
        if not CREDITS_FILE.exists():
            CREDITS_FILE.write_text(json.dumps({"keys": {}}, indent=2))

    def _load(self) -> dict:
        """Load the credits database."""
        return json.loads(CREDITS_FILE.read_text())

    def _save(self, data: dict):
        """Save the credits database."""
        CREDITS_FILE.write_text(json.dumps(data, indent=2))

    # ----- Key management -----

    def generate_key(self, plan: str = "starter", credits: int = 50, email: Optional[str] = None) -> str:
        """
        Generate a new API key with initial credits.

        Args:
            plan: One of 'starter', 'pro', 'unlimited'
            credits: Initial credit balance
            email: Optional email for the key owner

        Returns:
            The new API key string (ron_sk_...)
        """
        raw_key = secrets.token_urlsafe(32)
        api_key = f"ron_sk_{raw_key}"
        key_hash = self._hash_key(api_key)

        data = self._load()
        data["keys"][key_hash] = {
            "credits": credits if plan != "unlimited" else UNLIMITED_PLAN_CREDIT_DISPLAY,
            "plan": plan,
            "email": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used": None,
            "total_optimizations": 0,
        }
        self._save(data)

        logger.info("Generated new %s key for %s", plan, email or "unknown")
        return api_key

    def is_valid_key(self, api_key: str) -> bool:
        """Check if an API key exists and is valid."""
        key_hash = self._hash_key(api_key)
        data = self._load()
        return key_hash in data["keys"]

    # ----- Credit operations -----

    def get_credits(self, api_key: str) -> int:
        """Get remaining credits for an API key."""
        entry = self._get_entry(api_key)
        if entry is None:
            return 0
        return entry["credits"]

    def get_plan(self, api_key: str) -> str:
        """Get the plan name for an API key."""
        entry = self._get_entry(api_key)
        if entry is None:
            return "unknown"
        return entry["plan"]

    def use_credit(self, api_key: str) -> bool:
        """
        Deduct 1 credit. Returns True if successful, False if no credits remain.
        Unlimited plans always succeed without deducting.
        """
        key_hash = self._hash_key(api_key)
        data = self._load()
        entry = data["keys"].get(key_hash)

        if entry is None:
            return False

        # Unlimited plans do not deduct
        if entry["plan"] == "unlimited":
            entry["last_used"] = datetime.now(timezone.utc).isoformat()
            entry["total_optimizations"] += 1
            self._save(data)
            return True

        if entry["credits"] <= 0:
            return False

        entry["credits"] -= 1
        entry["last_used"] = datetime.now(timezone.utc).isoformat()
        entry["total_optimizations"] += 1
        self._save(data)

        logger.info(
            "Credit used for key %s... (%d remaining)",
            key_hash[:8],
            entry["credits"],
        )
        return True

    def add_credits(self, api_key: str, amount: int):
        """Add credits to an existing key (e.g., after a Stripe purchase)."""
        key_hash = self._hash_key(api_key)
        data = self._load()
        entry = data["keys"].get(key_hash)

        if entry is None:
            raise ValueError("Invalid API key")

        entry["credits"] += amount
        self._save(data)

        logger.info("Added %d credits to key %s...", amount, key_hash[:8])

    # ----- Internal helpers -----

    def _hash_key(self, api_key: str) -> str:
        """Hash an API key for storage. We never store raw keys."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def _get_entry(self, api_key: str) -> Optional[dict]:
        """Look up a key entry by API key."""
        key_hash = self._hash_key(api_key)
        data = self._load()
        return data["keys"].get(key_hash)
