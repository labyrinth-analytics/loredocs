#!/usr/bin/env python3
"""Rebuild LoreDocs auto-generated document relationships (SH-104427 / SH-104432).

The SH-103637 autolink quality fix (same-vault cooccurrence, threshold 5,
embedding-on-text-not-name) shipped forward-only. Existing stores still hold
pre-fix ``auto:cooccurrence`` and ``auto:embedding`` rows -- including
cross-vault noise that drags ``vault_find_related`` relevance below target.

This script purges every ``label LIKE 'auto:%'`` row in ``doc_links`` and
regenerates them with the current logic for all non-deleted documents.
Explicit (manual) links are never touched. The operation is idempotent:
running it twice yields a byte-identical ``doc_links`` table.

Usage:
    # Dry run -- count auto-links that would be purged and docs to process
    python scripts/relink_autolinks.py --dry-run

    # Relink cooccurrence links only (Free tier, or Pro without Lance index)
    python scripts/relink_autolinks.py

    # Relink cooccurrence + embedding links (Pro tier with Lance index)
    python scripts/relink_autolinks.py --include-embeddings

    # Custom root (e.g. for testing)
    python scripts/relink_autolinks.py --root /tmp/test-loredocs

Exit codes: 0 = success, 1 = error (DB missing, import failure, etc.).
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".loredocs"


def _find_root(override: Path = None) -> Path:
    """Resolve the LoreDocs data root."""
    if override:
        return override
    env_root = None
    try:
        env_root = os.environ.get("LOREDOCS_ROOT")
    except Exception:
        pass
    if env_root:
        return Path(env_root)
    return DEFAULT_ROOT


def _count_autolinks(db_path: Path) -> dict:
    """Count auto-generated and explicit doc_links for dry-run reporting."""
    conn = sqlite3.connect(str(db_path))
    try:
        auto = conn.execute(
            "SELECT COUNT(*) FROM doc_links WHERE label LIKE 'auto:%'"
        ).fetchone()[0]
        explicit = conn.execute(
            "SELECT COUNT(*) FROM doc_links WHERE label NOT LIKE 'auto:%'"
        ).fetchone()[0]
        cross_vault_auto = conn.execute(
            "SELECT COUNT(*) FROM doc_links "
            "WHERE label LIKE 'auto:%' AND source_vault_id != target_vault_id"
        ).fetchone()[0]
        docs = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE deleted = 0"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "auto": auto,
        "explicit": explicit,
        "cross_vault_auto": cross_vault_auto,
        "docs": docs,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild LoreDocs auto-generated document relationships.",
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="LoreDocs data root (default: ~/.loredocs/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count auto-links to purge and docs to process, then exit.",
    )
    parser.add_argument(
        "--include-embeddings", action="store_true",
        help="Also regenerate auto:embedding links (requires Pro tier + Lance "
             "index). Without this flag, only auto:cooccurrence links are "
             "regenerated and existing auto:embedding rows are still purged.",
    )
    args = parser.parse_args()

    root = _find_root(args.root)
    print(f"LoreDocs root: {root}")

    db_path = root / "loredocs.db"
    if not db_path.exists():
        print(f"[ERROR] Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    counts = _count_autolinks(db_path)
    print(f"  auto-links (to purge):       {counts['auto']}")
    print(f"    of which cross-vault:      {counts['cross_vault_auto']}")
    print(f"  explicit links (preserved):  {counts['explicit']}")
    print(f"  non-deleted documents:       {counts['docs']}")

    if args.dry_run:
        print("Dry run -- no changes made.")
        return

    if counts["auto"] == 0 and counts["docs"] == 0:
        print("Nothing to do (no auto-links, no documents).")
        return

    # Import VaultStorage from the package.
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from loredocs.storage import VaultStorage
    except ImportError as exc:
        print(f"[ERROR] Could not import VaultStorage: {exc}", file=sys.stderr)
        print("Ensure LoreDocs is installed:", file=sys.stderr)
        print("  pip install loredocs", file=sys.stderr)
        sys.exit(1)

    storage = VaultStorage(root=root)
    print("Purging auto-links and regenerating ...")
    try:
        result = storage.relink_autolinks(
            include_embeddings=args.include_embeddings,
        )
    except Exception as exc:
        print(f"[ERROR] Relink failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Purged {result['purged']} auto-links.")
    print(f"[OK] Regenerated {result['regenerated']} auto-links "
          f"across {result['docs_processed']} documents.")
    if result["embedding_skipped"]:
        print("[NOTE] Embedding links were skipped "
              "(no --include-embeddings, Free tier, or Lance index unavailable).")
    else:
        print("[OK] Embedding links regenerated.")

    # Post-condition verification: zero cross-vault auto-links remain.
    after = _count_autolinks(db_path)
    if after["cross_vault_auto"] > 0:
        print(
            f"[WARN] {after['cross_vault_auto']} cross-vault auto-links remain "
            "after relink -- investigate before relying on vault_find_related.",
            file=sys.stderr,
        )
    print(f"[VERIFY] cross-vault auto-links after relink: "
          f"{after['cross_vault_auto']}")


if __name__ == "__main__":
    main()