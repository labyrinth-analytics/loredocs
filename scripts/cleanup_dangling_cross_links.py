#!/usr/bin/env python3
"""
Clean up dangling cross-product links from loredocs database.

Dangling links are cross_product_links rows where the source or target
entity no longer exists. This can happen when sessions are deleted or
when manual links reference non-existent sessions.

Usage:
    python3 cleanup_dangling_cross_links.py [--dry-run] [--loreconvo-db PATH]

Options:
    --dry-run           Show what would be deleted without making changes
    --loreconvo-db PATH Path to loreconvo sessions.db (auto-discovered by default)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

def discover_loreconvo_db():
    """Find loreconvo sessions.db in standard locations."""
    home = Path.home()
    candidates = [
        home / ".loreconvo" / "sessions.db",
    ]
    # Check env override
    if os.getenv("LORECONVO_DB_PATH"):
        candidates.insert(0, Path(os.getenv("LORECONVO_DB_PATH")))

    for path in candidates:
        if path.exists():
            return path
    return None

def get_loredocs_db():
    """Get loredocs database path."""
    home = Path.home()
    db = home / ".loredocs" / "loredocs.db"
    if not db.exists():
        print(f"[ERROR] LoreDocs database not found at {db}")
        return None
    return db

def cleanup_dangling_links(loredocs_db, loreconvo_db=None, dry_run=False):
    """
    Find and optionally delete dangling cross_product_links.

    Returns tuple: (deleted_count, errors)
    """
    ld = sqlite3.connect(str(loredocs_db))
    ld.row_factory = sqlite3.Row
    ld_cursor = ld.cursor()

    # Track stats
    dangling_to_missing_loreconvo = 0
    dangling_to_missing_loredocs = 0

    # If loreconvo is available, use it for cross-database validation
    lc = None
    if loreconvo_db:
        try:
            lc = sqlite3.connect(f"file:{loreconvo_db}?mode=ro", uri=True, timeout=2.0)
            lc.row_factory = sqlite3.Row
            lc.execute("SELECT 1 FROM sessions LIMIT 1")
        except Exception as e:
            print(f"[WARN] Could not open loreconvo DB {loreconvo_db}: {e}")
            print("[WARN] Will only check loredocs internal consistency")
            lc = None

    if lc:
        # Count and optionally delete loreconvo-to-loredocs links where session doesn't exist
        lc_cursor = lc.cursor()
        ld_cursor.execute("""
            SELECT COUNT(*) FROM cross_product_links cpl
            WHERE cpl.source_product = 'loreconvo'
            AND cpl.source_id NOT IN (SELECT id FROM lc.sessions)
        """)

        # Actually, can't do cross-DB query this way. Need to attach
        ld.execute(f"ATTACH DATABASE '{loreconvo_db}' AS lc")
        ld_cursor.execute("""
            SELECT COUNT(*) FROM cross_product_links cpl
            WHERE cpl.source_product = 'loreconvo'
            AND cpl.source_id NOT IN (SELECT id FROM lc.sessions)
        """)
        dangling_to_missing_loreconvo = ld_cursor.fetchone()[0]

    # Count loredocs-to-missing-docs (target_id not in documents)
    ld_cursor.execute("""
        SELECT COUNT(*) FROM cross_product_links cpl
        WHERE cpl.target_product = 'loredocs'
        AND cpl.target_id NOT IN (SELECT id FROM documents WHERE deleted = 0)
    """)
    dangling_to_missing_loredocs = ld_cursor.fetchone()[0]

    print(f"\n[REPORT] Dangling cross_product_links found:")
    if loreconvo_db:
        print(f"  - Links to missing loreconvo sessions: {dangling_to_missing_loreconvo}")
    print(f"  - Links to missing/deleted loredocs docs: {dangling_to_missing_loredocs}")

    total_dangling = dangling_to_missing_loreconvo + dangling_to_missing_loredocs
    print(f"  - Total: {total_dangling}")

    if total_dangling == 0:
        print("\n[OK] No dangling links found")
        return 0

    if dry_run:
        print(f"\n[DRY-RUN] Would delete {total_dangling} dangling cross_product_links")
        print("[DRY-RUN] Run without --dry-run to apply deletions")
        return 0

    # Delete dangling links
    deleted = 0

    if lc:
        ld_cursor.execute("""
            DELETE FROM cross_product_links
            WHERE source_product = 'loreconvo'
            AND source_id NOT IN (SELECT id FROM lc.sessions)
        """)
        deleted += ld_cursor.rowcount
        print(f"[DELETED] {ld_cursor.rowcount} links to missing sessions")

    ld_cursor.execute("""
        DELETE FROM cross_product_links
        WHERE target_product = 'loredocs'
        AND target_id NOT IN (SELECT id FROM documents WHERE deleted = 0)
    """)
    deleted += ld_cursor.rowcount
    print(f"[DELETED] {ld_cursor.rowcount} links to missing/deleted docs")

    ld.commit()
    ld.close()
    if lc:
        lc.close()

    print(f"\n[OK] Deleted {deleted} dangling cross_product_links")
    return deleted

def main():
    parser = argparse.ArgumentParser(
        description="Clean up dangling cross-product links from loredocs database"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("--loreconvo-db", help="Path to loreconvo sessions.db")
    args = parser.parse_args()

    # Find databases
    loredocs_db = get_loredocs_db()
    if not loredocs_db:
        return 1

    loreconvo_db = args.loreconvo_db
    if not loreconvo_db:
        loreconvo_db = discover_loreconvo_db()
        if loreconvo_db:
            print(f"[INFO] Found loreconvo at {loreconvo_db}")
        else:
            print("[WARN] LoreConvo database not found; will check loredocs consistency only")

    print(f"[INFO] LoreDocs database: {loredocs_db}")

    # Run cleanup
    deleted = cleanup_dangling_links(loredocs_db, loreconvo_db, args.dry_run)

    return 0

if __name__ == "__main__":
    sys.exit(main())
