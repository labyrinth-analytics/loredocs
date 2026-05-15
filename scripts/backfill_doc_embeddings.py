#!/usr/bin/env python3
"""Backfill the LoreDocs LanceDB semantic search index for existing documents.

Run this once after installing LoreDocs Pro deps to make existing documents
searchable via semantic (vector) search. New documents added after install
are indexed automatically; only pre-existing documents need the backfill.

Usage:
    # Dry run -- count documents that would be indexed
    python scripts/backfill_doc_embeddings.py --dry-run

    # Index all documents in the default LoreDocs root (~/.loredocs/)
    python scripts/backfill_doc_embeddings.py

    # Index with a custom root (e.g. for testing)
    python scripts/backfill_doc_embeddings.py --root /tmp/test-loredocs
"""
import argparse
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
        import os
        env_root = os.environ.get("LOREDOCS_ROOT")
    except Exception:
        pass
    if env_root:
        return Path(env_root)
    return DEFAULT_ROOT


def _load_docs(root: Path):
    """Return list of doc dicts from SQLite."""
    db_path = root / "loredocs.db"
    if not db_path.exists():
        print(f"[ERROR] Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, vault_id, name FROM documents WHERE deleted = 0"
    ).fetchall()
    conn.close()

    docs = []
    vaults_dir = root / "vaults"
    for row in rows:
        extracted_path = vaults_dir / row["vault_id"] / "docs" / row["id"] / "extracted.txt"
        if not extracted_path.exists():
            continue
        try:
            text = extracted_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[WARN] Could not read {extracted_path}: {exc}", file=sys.stderr)
            continue
        if text.strip():
            docs.append({
                "doc_id": row["id"],
                "vault_id": row["vault_id"],
                "name": row["name"],
                "text": text,
            })
    return docs


def main():
    parser = argparse.ArgumentParser(description="Backfill LoreDocs semantic search index")
    parser.add_argument("--root", type=Path, default=None,
                        help="LoreDocs data root (default: ~/.loredocs/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count docs that would be indexed, then exit")
    args = parser.parse_args()

    root = _find_root(args.root)
    print(f"LoreDocs root: {root}")

    docs = _load_docs(root)
    print(f"Documents with extracted text: {len(docs)}")

    if args.dry_run:
        print("Dry run -- no index changes made.")
        return

    if not docs:
        print("No documents to index.")
        return

    # Import semantic_search from the package
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from loredocs.semantic_search import DocLanceIndex
    except ImportError as exc:
        print(f"[ERROR] Could not import DocLanceIndex: {exc}", file=sys.stderr)
        print("Ensure LoreDocs is installed and Pro deps are available:", file=sys.stderr)
        print("  pip install loredocs[pro]", file=sys.stderr)
        sys.exit(1)

    lance_dir = root / "docs.lance"
    index = DocLanceIndex(lance_dir)

    print(f"Building index at {lance_dir} ...")
    try:
        chunk_count = index.rebuild(docs)
    except Exception as exc:
        print(f"[ERROR] Rebuild failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Indexed {len(docs)} documents ({chunk_count} chunks) into {lance_dir}")


if __name__ == "__main__":
    main()
