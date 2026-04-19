"""
Direct LoreDocs query tool -- fallback when MCP tools are unavailable.

Provides vault_list, vault_info (inject_summary), vault_search,
vault_add_document, vault_create, vault_update_doc, vault_remove_doc,
vault_archive, and vault_restore operations directly against the LoreDocs
SQLite database. Use this when the LoreDocs MCP server is not reachable
(e.g., in scheduled tasks or batch scripts).

Usage:
    # List all vaults (equivalent to vault_list)
    python scripts/query_loredocs.py --list

    # Show vault details + document manifest (equivalent to vault_inject_summary)
    python scripts/query_loredocs.py --info "My Project Docs"

    # Search documents across all vaults
    python scripts/query_loredocs.py --search "architecture"

    # Add a text/markdown document to a vault
    python scripts/query_loredocs.py --add-doc \
        --vault "My Project Docs" \
        --name "Architecture Overview" \
        --file docs/architecture.md \
        --tags '["architecture", "design"]' \
        --category "architecture"

    # Add a document from stdin (pipe content in)
    echo "# My Doc" | python scripts/query_loredocs.py --add-doc \
        --vault "My Project Docs" \
        --name "Quick Note" \
        --stdin

    # Create a new vault
    python scripts/query_loredocs.py --create-vault \
        --name "My New Vault" \
        --description "Stores project docs" \
        --tags '["project", "2026"]'

    # Update a document's metadata or content
    python scripts/query_loredocs.py --update-doc \
        --doc-id abc123def456 \
        --name "New Title" \
        --priority "authoritative"

    # Update a document's content from a file
    python scripts/query_loredocs.py --update-doc \
        --doc-id abc123def456 \
        --file docs/updated.md

    # Soft-delete a document
    python scripts/query_loredocs.py --delete-doc --doc-id abc123def456

    # Archive a vault (soft delete)
    python scripts/query_loredocs.py --archive --vault "Old Project Docs"

    # Restore (unarchive) a vault
    python scripts/query_loredocs.py --restore --vault "Old Project Docs"
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# -- DB discovery --

def _find_loredocs_db():
    """Find the LoreDocs database, checking common locations.

    Mounted paths are checked FIRST. In Cowork VMs, os.path.expanduser("~")
    resolves to the ephemeral VM home (e.g. /sessions/sharp-adoring-dijkstra/),
    NOT Debbie's Mac home. Writing to VM ~ loses all data when the session ends.
    Checking /sessions/*/mnt/.loredocs/ first ensures we find the Mac-backed
    mount when running in a Cowork VM.
    """
    # Cowork VM mount paths FIRST -- VM ~ is ephemeral, mount is Debbie's Mac
    candidates = sorted(glob.glob("/sessions/*/mnt/.loredocs/loredocs.db"))
    # VM home fallback (used in Claude Code on Debbie's Mac where ~ IS the Mac home)
    candidates += [os.path.expanduser("~/.loredocs/loredocs.db")]

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _find_loredocs_root(db_path):
    """Derive the LoreDocs root dir from the DB path."""
    return str(Path(db_path).parent)


def _connect(db_path=None):
    """Connect to LoreDocs DB, auto-discovering if no path given."""
    path = db_path or _find_loredocs_db()
    if not path:
        print("ERROR: Could not find LoreDocs loredocs.db", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn, path


def _fmt_size(size_bytes):
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _parse_tags(s):
    """Parse tags field: handles JSON array or legacy comma-separated string."""
    if not s:
        return []
    try:
        result = json.loads(s)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, ValueError):
        return [t.strip() for t in s.split(",") if t.strip()]


def _resolve_vault(conn, vault_ref):
    """Resolve a vault by ID or name (case-insensitive). Returns row dict or None."""
    # Try exact ID match first
    row = conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_ref,)).fetchone()
    if row:
        return dict(row)

    # Try case-insensitive name match
    row = conn.execute(
        "SELECT * FROM vaults WHERE LOWER(name) = LOWER(?)", (vault_ref,)
    ).fetchone()
    if row:
        return dict(row)

    return None


# -- vault_list --

def cmd_list(args):
    """List all vaults with summary stats."""
    conn, db_path = _connect(args.db_path)

    query = "SELECT * FROM vaults"
    if not args.include_archived:
        query += " WHERE archived = 0"
    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query).fetchall()

    if not rows:
        print("No vaults found.")
        return

    print("# Your Vaults\n")
    for row in rows:
        vault_id = row["id"]
        stats = conn.execute(
            """SELECT COUNT(*) as doc_count, COALESCE(SUM(file_size_bytes), 0) as total_size
               FROM documents WHERE vault_id = ? AND deleted = 0""",
            (vault_id,)
        ).fetchone()

        status = " [ARCHIVED]" if row["archived"] else ""
        print(f"## {row['name']}{status} (`{vault_id}`)")
        if row["description"]:
            print(f"  {row['description']}")
        print(f"  - Documents: {stats['doc_count']} | Size: {_fmt_size(stats['total_size'])}")
        tags = _parse_tags(row["tags"])
        if tags:
            print(f"  - Tags: {', '.join(tags)}")
        linked = _parse_tags(row["linked_projects"])
        if linked:
            print(f"  - Linked projects: {', '.join(linked)}")
        print(f"  - Last updated: {row['updated_at'][:10]}")
        print()

    conn.close()


# -- vault_info / vault_inject_summary --

def cmd_info(args):
    """Show vault details and full document manifest."""
    conn, db_path = _connect(args.db_path)

    vault = _resolve_vault(conn, args.info)
    if not vault:
        print(f"Error: Vault '{args.info}' not found.")
        conn.close()
        return

    vault_id = vault["id"]
    stats = conn.execute(
        """SELECT COUNT(*) as doc_count, COALESCE(SUM(file_size_bytes), 0) as total_size
           FROM documents WHERE vault_id = ? AND deleted = 0""",
        (vault_id,)
    ).fetchone()

    docs = conn.execute(
        """SELECT id, name, category, priority, tags, notes, updated_at, file_size_bytes
           FROM documents WHERE vault_id = ? AND deleted = 0
           ORDER BY updated_at DESC""",
        (vault_id,)
    ).fetchall()

    print(f"# {vault['name']} (`{vault_id}`)")
    if vault["description"]:
        print(f"\n{vault['description']}")
    print(f"\nDocuments: {stats['doc_count']} | Total size: {_fmt_size(stats['total_size'])}")
    print(f"Created: {vault['created_at'][:10]} | Updated: {vault['updated_at'][:10]}")

    tags = _parse_tags(vault["tags"])
    if tags:
        print(f"Tags: {', '.join(tags)}")

    if docs:
        print(f"\n## Documents ({len(docs)})\n")
        for d in docs:
            dtags = _parse_tags(d["tags"])
            tag_str = f" [{', '.join(dtags)}]" if dtags else ""
            print(f"- **{d['name']}** ({d['category']}, {d['priority']}){tag_str}")
            print(f"  ID: {d['id']} | Size: {_fmt_size(d['file_size_bytes'])} | Updated: {d['updated_at'][:10]}")
            if d["notes"]:
                print(f"  Notes: {d['notes'][:100]}")
    else:
        print("\nNo documents in this vault.")

    conn.close()


# -- vault_search --

def cmd_search(args):
    """Search documents across all vaults by keyword."""
    conn, db_path = _connect(args.db_path)

    # Use FTS if available, fall back to LIKE
    try:
        rows = conn.execute(
            """SELECT d.id, d.vault_id, d.name, d.category, d.tags, d.notes,
                      d.updated_at, d.file_size_bytes, v.name as vault_name
               FROM doc_fts f
               JOIN documents d ON f.doc_id = d.id
               JOIN vaults v ON d.vault_id = v.id
               WHERE doc_fts MATCH ? AND d.deleted = 0
               ORDER BY d.updated_at DESC LIMIT ?""",
            (args.search, args.limit)
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS match failed, fall back to LIKE
        pattern = f"%{args.search}%"
        rows = conn.execute(
            """SELECT d.id, d.vault_id, d.name, d.category, d.tags, d.notes,
                      d.updated_at, d.file_size_bytes, v.name as vault_name
               FROM documents d
               JOIN vaults v ON d.vault_id = v.id
               WHERE d.deleted = 0 AND (d.name LIKE ? OR d.notes LIKE ?)
               ORDER BY d.updated_at DESC LIMIT ?""",
            (pattern, pattern, args.limit)
        ).fetchall()

    conn.close()

    if not rows:
        print(f"No documents matching '{args.search}'.")
        return

    print(f"Found {len(rows)} document(s) matching '{args.search}':\n")
    for d in rows:
        dtags = _parse_tags(d["tags"])
        tag_str = f" [{', '.join(dtags)}]" if dtags else ""
        print(f"- **{d['name']}** in vault '{d['vault_name']}'{tag_str}")
        print(f"  ID: {d['id']} | Category: {d['category']} | Size: {_fmt_size(d['file_size_bytes'])}")
        if d["notes"]:
            print(f"  Notes: {d['notes'][:100]}")
        print()


# -- vault_add_document --

def cmd_add_doc(args):
    """Add a document to a vault."""
    conn, db_path = _connect(args.db_path)
    root = _find_loredocs_root(db_path)

    vault = _resolve_vault(conn, args.vault)
    if not vault:
        print(f"Error: Vault '{args.vault}' not found.")
        conn.close()
        return

    vault_id = vault["id"]

    # Read content
    if args.stdin:
        content = sys.stdin.buffer.read()
        filename = args.name.replace(" ", "_").lower() + ".md"
    elif args.file:
        filepath = Path(args.file)
        if not filepath.is_file():
            print(f"Error: File '{args.file}' not found.")
            conn.close()
            return
        content = filepath.read_bytes()
        filename = filepath.name
    else:
        print("Error: Must specify --file or --stdin for document content.")
        conn.close()
        return

    # Validate filename
    if not filename or '..' in filename or '\x00' in filename or os.path.isabs(filename):
        print("Error: Invalid filename.")
        conn.close()
        return

    # Parse tags
    tags = []
    if args.tags:
        try:
            parsed = json.loads(args.tags)
            if isinstance(parsed, list):
                tags = parsed
        except (json.JSONDecodeError, TypeError):
            tags = [args.tags]

    doc_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()
    ext = Path(filename).suffix.lower()
    category = args.category or "general"
    priority = args.priority or "normal"
    notes = args.notes or ""

    # Write file to disk
    vaults_dir = Path(root) / "vaults"
    doc_dir = vaults_dir / vault_id / "docs" / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "history").mkdir(exist_ok=True)

    current_file = doc_dir / f"current{ext}"
    current_file.write_bytes(content)

    # Extract text for search (simple: just decode if text-like)
    try:
        extracted = content.decode("utf-8")
    except UnicodeDecodeError:
        extracted = ""

    (doc_dir / "extracted.txt").write_text(extracted, encoding="utf-8")

    # Write metadata
    meta = {
        "id": doc_id,
        "vault_id": vault_id,
        "name": args.name,
        "original_filename": filename,
        "file_extension": ext,
        "category": category,
        "priority": priority,
        "tags": tags,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "file_size_bytes": len(content),
        "version_count": 1,
    }
    (doc_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    # Insert into database
    conn.execute(
        """INSERT INTO documents
           (id, vault_id, name, original_filename, file_extension,
            category, priority, tags, notes, created_at, updated_at,
            file_size_bytes, version_count, deleted)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (doc_id, vault_id, args.name, filename, ext, category, priority,
         json.dumps(tags), notes, now, now, len(content), 1)
    )

    # Index in FTS
    conn.execute(
        """INSERT INTO doc_fts (doc_id, vault_id, name, content, tags, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (doc_id, vault_id, args.name, extracted, " ".join(tags), notes)
    )

    # Update vault timestamp
    conn.execute(
        "UPDATE vaults SET updated_at = ? WHERE id = ?", (now, vault_id)
    )
    conn.commit()
    conn.close()

    print(f"Added document '{args.name}' to vault '{vault['name']}'")
    print(f"  doc_id: {doc_id}")
    print(f"  filename: {filename}")
    print(f"  size: {_fmt_size(len(content))}")


# -- vault_create --

def cmd_create_vault(args):
    """Create a new vault."""
    conn, db_path = _connect(args.db_path)

    # Parse tags and linked_projects
    tags = []
    if args.tags:
        try:
            parsed = json.loads(args.tags)
            if isinstance(parsed, list):
                tags = parsed
        except (json.JSONDecodeError, TypeError):
            tags = [args.tags]

    linked_projects = []
    if args.linked_projects:
        try:
            parsed = json.loads(args.linked_projects)
            if isinstance(parsed, list):
                linked_projects = parsed
        except (json.JSONDecodeError, TypeError):
            linked_projects = [args.linked_projects]

    vault_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()
    description = args.description or ""

    # Create vault directory
    root = _find_loredocs_root(db_path)
    vault_dir = Path(root) / "vaults" / vault_id / "docs"
    vault_dir.mkdir(parents=True, exist_ok=True)

    conn.execute(
        """INSERT INTO vaults (id, name, description, created_at, updated_at, tags, linked_projects)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (vault_id, args.name, description, now, now,
         json.dumps(tags), json.dumps(linked_projects))
    )
    conn.commit()
    conn.close()

    print(f"Created vault '{args.name}'")
    print(f"  vault_id: {vault_id}")
    if description:
        print(f"  description: {description}")
    if tags:
        print(f"  tags: {', '.join(tags)}")
    if linked_projects:
        print(f"  linked_projects: {', '.join(linked_projects)}")


# -- vault_update_doc --

def cmd_update_doc(args):
    """Update a document's content or metadata."""
    conn, db_path = _connect(args.db_path)
    root = _find_loredocs_root(db_path)

    # Verify document exists
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ? AND deleted = 0", (args.doc_id,)
    ).fetchone()
    if not row:
        print(f"Error: Document '{args.doc_id}' not found.")
        conn.close()
        return

    vault_id = row["vault_id"]
    now = datetime.now(timezone.utc).isoformat()
    doc_dir = Path(root) / "vaults" / vault_id / "docs" / args.doc_id
    ext = row["file_extension"]
    current_file = doc_dir / f"current{ext}"
    version_count = row["version_count"]

    # Handle content update
    new_content = None
    if args.file:
        filepath = Path(args.file)
        if not filepath.is_file():
            print(f"Error: File '{args.file}' not found.")
            conn.close()
            return
        new_content = filepath.read_bytes()
    elif args.stdin:
        new_content = sys.stdin.buffer.read()

    if new_content is not None:
        # Version the current file first
        if current_file.exists():
            history_dir = doc_dir / "history"
            history_dir.mkdir(exist_ok=True)
            history_file = history_dir / f"v{version_count}{ext}"
            import shutil
            shutil.copy2(current_file, history_file)
            version_count += 1
        current_file.write_bytes(new_content)
        try:
            extracted = new_content.decode("utf-8")
        except UnicodeDecodeError:
            extracted = ""
        (doc_dir / "extracted.txt").write_text(extracted, encoding="utf-8")
        file_size = len(new_content)
    else:
        file_size = row["file_size_bytes"]
        extracted_path = doc_dir / "extracted.txt"
        extracted = extracted_path.read_text(encoding="utf-8") if extracted_path.exists() else ""

    # Build update fields
    updates = {"updated_at": now, "version_count": version_count}
    if args.name is not None:
        updates["name"] = args.name
    if args.tags is not None:
        try:
            parsed = json.loads(args.tags)
            updates["tags"] = json.dumps(parsed if isinstance(parsed, list) else [args.tags])
        except (json.JSONDecodeError, TypeError):
            updates["tags"] = json.dumps([args.tags])
    if args.category is not None:
        updates["category"] = args.category
    if args.priority is not None:
        updates["priority"] = args.priority
    if args.notes is not None:
        updates["notes"] = args.notes
    if new_content is not None:
        updates["file_size_bytes"] = file_size

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [args.doc_id]
    conn.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", values)

    # Update FTS
    conn.execute("DELETE FROM doc_fts WHERE doc_id = ?", (args.doc_id,))
    final_name = args.name if args.name is not None else row["name"]
    final_tags_raw = updates.get("tags", row["tags"])
    final_tags = _parse_tags(final_tags_raw)
    final_notes = args.notes if args.notes is not None else (row["notes"] or "")
    conn.execute(
        """INSERT INTO doc_fts (doc_id, vault_id, name, content, tags, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.doc_id, vault_id, final_name, extracted, " ".join(final_tags), final_notes)
    )

    # Update vault timestamp
    conn.execute("UPDATE vaults SET updated_at = ? WHERE id = ?", (now, vault_id))
    conn.commit()
    conn.close()

    print(f"Updated document '{args.doc_id}'")
    if args.name:
        print(f"  name: {args.name}")
    if new_content is not None:
        print(f"  content updated ({_fmt_size(file_size)}, now at version {version_count})")


# -- vault_remove_doc --

def cmd_delete_doc(args):
    """Soft-delete a document."""
    conn, _db_path = _connect(args.db_path)

    row = conn.execute(
        "SELECT name FROM documents WHERE id = ? AND deleted = 0", (args.doc_id,)
    ).fetchone()
    if not row:
        print(f"Error: Document '{args.doc_id}' not found.")
        conn.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE documents SET deleted = 1, updated_at = ? WHERE id = ?",
        (now, args.doc_id)
    )
    conn.execute("DELETE FROM doc_fts WHERE doc_id = ?", (args.doc_id,))
    conn.commit()
    conn.close()

    print(f"Document '{row['name']}' ({args.doc_id}) has been removed (soft-deleted).")


# -- vault_archive --

def cmd_archive(args):
    """Archive a vault (soft delete -- hidden from list but restorable)."""
    conn, _db_path = _connect(args.db_path)

    vault = _resolve_vault(conn, args.vault)
    if not vault:
        print(f"Error: Vault '{args.vault}' not found.")
        conn.close()
        return

    if vault["archived"]:
        print(f"Vault '{vault['name']}' is already archived.")
        conn.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE vaults SET archived = 1, updated_at = ? WHERE id = ?",
        (now, vault["id"])
    )
    conn.commit()
    conn.close()

    print(f"Vault '{vault['name']}' has been archived.")
    print("  Use --list --include-archived to see it, or --restore to unarchive.")


# -- vault_restore (unarchive) --

def cmd_restore(args):
    """Restore (unarchive) a vault."""
    conn, _db_path = _connect(args.db_path)

    # Need to find archived vaults too -- _resolve_vault skips archived on name match
    # Try ID first, then case-insensitive name (including archived)
    row = conn.execute("SELECT * FROM vaults WHERE id = ?", (args.vault,)).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM vaults WHERE LOWER(name) = LOWER(?)", (args.vault,)
        ).fetchone()
    if not row:
        print(f"Error: Vault '{args.vault}' not found.")
        conn.close()
        return

    vault = dict(row)
    if not vault["archived"]:
        print(f"Vault '{vault['name']}' is not archived.")
        conn.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE vaults SET archived = 0, updated_at = ? WHERE id = ?",
        (now, vault["id"])
    )
    conn.commit()
    conn.close()

    print(f"Vault '{vault['name']}' has been restored (unarchived).")


# -- migrate-tags --

def cmd_migrate_tags(args):
    """One-time migration: normalize legacy comma-separated tags to JSON arrays."""
    conn, db_path = _connect(args.db_path)
    migrated_vaults = 0
    migrated_docs = 0

    rows = conn.execute(
        "SELECT id, tags FROM vaults WHERE tags IS NOT NULL AND tags != '' AND tags NOT LIKE '[%'"
    ).fetchall()
    for row in rows:
        tags = [t.strip() for t in row["tags"].split(",") if t.strip()]
        conn.execute("UPDATE vaults SET tags = ? WHERE id = ?", (json.dumps(tags), row["id"]))
        migrated_vaults += 1

    rows = conn.execute(
        "SELECT id, tags FROM documents WHERE tags IS NOT NULL AND tags != '' AND tags NOT LIKE '[%'"
    ).fetchall()
    for row in rows:
        tags = [t.strip() for t in row["tags"].split(",") if t.strip()]
        conn.execute("UPDATE documents SET tags = ? WHERE id = ?", (json.dumps(tags), row["id"]))
        migrated_docs += 1

    conn.commit()
    conn.close()
    print(f"Migration complete: {migrated_vaults} vault(s), {migrated_docs} document(s) updated.")


# -- CLI --

def main():
    parser = argparse.ArgumentParser(
        description="Direct LoreDocs query tool (fallback for MCP tools)"
    )
    parser.add_argument("--db-path", help="Explicit path to loredocs.db (auto-discovers if omitted)")

    # Mode flags
    parser.add_argument("--list", action="store_true", help="List all vaults (equivalent to vault_list)")
    parser.add_argument("--info", type=str, help="Show vault details by name or ID (equivalent to vault_inject_summary)")
    parser.add_argument("--search", type=str, help="Search documents by keyword")
    parser.add_argument("--add-doc", action="store_true", dest="add_doc", help="Add a document to a vault")
    parser.add_argument("--create-vault", action="store_true", dest="create_vault", help="Create a new vault")
    parser.add_argument("--update-doc", action="store_true", dest="update_doc", help="Update a document's content or metadata")
    parser.add_argument("--delete-doc", action="store_true", dest="delete_doc", help="Soft-delete a document")
    parser.add_argument("--archive", action="store_true", help="Archive a vault (soft delete, use with --vault)")
    parser.add_argument("--restore", action="store_true", help="Restore (unarchive) a vault (use with --vault)")
    parser.add_argument("--migrate-tags", action="store_true", dest="migrate_tags",
                        help="One-time migration: normalize legacy comma-separated tags to JSON arrays")
    parser.add_argument("--include-archived", action="store_true", dest="include_archived",
                        help="Include archived vaults in --list")

    # Search/list args
    parser.add_argument("--limit", type=int, default=10, help="Max results for search (default: 10)")

    # Vault/doc shared args
    parser.add_argument("--vault", type=str, help="Vault name or ID")
    parser.add_argument("--name", type=str, help="Vault or document name")
    parser.add_argument("--description", type=str, help="Vault description (for --create-vault)")
    parser.add_argument("--linked-projects", type=str, dest="linked_projects",
                        help="JSON list of linked project names (for --create-vault)")
    parser.add_argument("--doc-id", type=str, dest="doc_id", help="Document ID (for --update-doc, --delete-doc)")
    parser.add_argument("--file", type=str, help="Path to file (for --add-doc, --update-doc)")
    parser.add_argument("--stdin", action="store_true", help="Read content from stdin (for --add-doc, --update-doc)")
    parser.add_argument("--tags", type=str, help="JSON list of tags")
    parser.add_argument("--category", type=str, help="Document category (default: general)")
    parser.add_argument("--priority", type=str, help="Document priority (default: normal)")
    parser.add_argument("--notes", type=str, help="Document notes")

    args = parser.parse_args()

    if args.migrate_tags:
        cmd_migrate_tags(args)
    elif args.create_vault:
        if not args.name:
            parser.error("--create-vault requires --name")
        cmd_create_vault(args)
    elif args.update_doc:
        if not args.doc_id:
            parser.error("--update-doc requires --doc-id")
        cmd_update_doc(args)
    elif args.delete_doc:
        if not args.doc_id:
            parser.error("--delete-doc requires --doc-id")
        cmd_delete_doc(args)
    elif args.archive:
        if not args.vault:
            parser.error("--archive requires --vault")
        cmd_archive(args)
    elif args.restore:
        if not args.vault:
            parser.error("--restore requires --vault")
        cmd_restore(args)
    elif args.add_doc:
        if not args.vault or not args.name:
            parser.error("--add-doc requires --vault and --name")
        cmd_add_doc(args)
    elif args.info:
        cmd_info(args)
    elif args.search:
        cmd_search(args)
    elif args.list:
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
