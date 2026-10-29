#!/usr/bin/env python3
"""
Clean up dangling cross-product links from the LoreDocs database.

Dangling links are cross_product_links rows where the LoreConvo session
(source or target) no longer exists.  Only link_type='auto' rows are
deleted; manual links are never touched.

This tool also trims over-cap docs -- docs whose auto session links
exceed the lifetime cap (500).  Trimming keeps the top 500 by
similarity_score and removes the rest.

DRY RUN IS THE DEFAULT.  No rows are deleted unless --execute is passed.
A timestamped backup of loredocs.db is taken before any deletion.

The tool REFUSES to run if the LoreConvo DB cannot be discovered or if
its sessions table is empty -- a wrong path would make every link look
dangling and wipe all of them.

Usage:
    # Dry run (default): report counts, delete nothing
    python3 scripts/cleanup_dangling_cross_links.py

    # Execute prune: delete dangling auto links (with backup)
    python3 scripts/cleanup_dangling_cross_links.py --execute

    # Dry-run trim over-cap docs
    python3 scripts/cleanup_dangling_cross_links.py --trim

    # Execute trim over-cap docs (with backup)
    python3 scripts/cleanup_dangling_cross_links.py --trim --execute

    # Execute both prune and trim
    python3 scripts/cleanup_dangling_cross_links.py --trim --execute

Options:
    --execute       Actually delete rows (default is dry-run)
    --trim           Also trim over-cap docs (dry-run unless --execute)
    --loreconvo-db   Path to loreconvo sessions.db (auto-discovered by default)
    --loredocs-root  Override LoreDocs data root (defaults to ~/.loredocs)
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure the loredocs package is importable when run from the repo.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


def main():
    from loredocs.storage import VaultStorage, DiscoveryError

    parser = argparse.ArgumentParser(
        description=(
            "Clean up dangling cross-product links from LoreDocs. "
            "Dry-run by default; --execute to delete."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete rows (default is dry-run)",
    )
    parser.add_argument(
        "--trim",
        action="store_true",
        help="Also trim over-cap docs (dry-run unless --execute)",
    )
    parser.add_argument(
        "--loreconvo-db",
        help="Path to loreconvo sessions.db (auto-discovered by default)",
    )
    parser.add_argument(
        "--loredocs-root",
        default=None,
        help="Override LoreDocs data root (defaults to ~/.loredocs)",
    )
    args = parser.parse_args()

    # Override LoreDocs root if requested.
    if args.loredocs_root:
        os.environ["LOREDOCS_ROOT"] = args.loredocs_root

    # Override LoreConvo DB path if requested.
    if args.loreconvo_db:
        os.environ["LORECONVO_DB_PATH"] = args.loreconvo_db

    # Determine the LoreDocs root.
    root = Path(args.loredocs_root) if args.loredocs_root else None
    storage = VaultStorage(root=root)

    mode = "EXECUTE" if args.execute else "DRY-RUN"

    # ------------------------------------------------------------------
    # Prune dangling auto links
    # ------------------------------------------------------------------
    print(f"[{mode}] Pruning dangling auto cross-product links ...")
    print(f"  LoreDocs DB: {storage.db_path}")
    try:
        result = storage.prune_dangling_auto_links(execute=args.execute)
    except DiscoveryError as exc:
        print(f"[REFUSED] {exc}")
        return 1

    if not result["ok"]:
        print(f"[REFUSED] {result['error']}")
        return 1

    print(f"  Total auto links:       {result['total_auto']}")
    print(f"  Dangling auto links:    {result['dangling_auto']}")
    print(f"  Dangling manual (left): {result['dangling_manual']}")
    print(f"  Over-cap docs:          {result['over_cap_docs']}")
    if args.execute:
        print(f"  Deleted:                {result['deleted']}")
        if result.get("backup_path"):
            print(f"  Backup:                 {result['backup_path']}")
    else:
        print("  (dry-run -- no rows deleted)")
        if result["dangling_auto"] > 0:
            print("  Run with --execute to delete dangling auto links.")

    # ------------------------------------------------------------------
    # Trim over-cap docs (optional)
    # ------------------------------------------------------------------
    if args.trim:
        print(f"\n[{mode}] Trimming over-cap docs ...")
        trim_result = storage.trim_overcap_auto_links(execute=args.execute)
        if not trim_result["ok"]:
            print(f"[REFUSED] {trim_result['error']}")
            return 1
        print(f"  Over-cap docs:   {trim_result['over_cap_docs']}")
        if args.execute:
            print(f"  Rows trimmed:    {trim_result['total_trimmed']}")
            if trim_result.get("backup_path"):
                print(f"  Backup:          {trim_result['backup_path']}")
        else:
            print(f"  Would trim:      {trim_result['over_cap_docs']} doc(s)")
            print("  (dry-run -- no rows deleted)")

    # ------------------------------------------------------------------
    # Idempotency check (only when executing prune)
    # ------------------------------------------------------------------
    if args.execute and result["dangling_auto"] > 0:
        print("\n[VERIFY] Running again to confirm idempotency ...")
        verify = storage.prune_dangling_auto_links(execute=False)
        if verify["ok"]:
            print(f"  Dangling auto links after prune: {verify['dangling_auto']}")
            if verify["dangling_auto"] != 0:
                print("[WARN] Idempotency check: dangling links remain.")
            else:
                print("  [OK] Idempotent -- 0 dangling links on second run.")

    print("\n[OK] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())