"""LoreDocs CLI -- vault and document management from the command line."""
import json
import sys
from pathlib import Path

import click

from .storage import VaultStorage


def _storage() -> VaultStorage:
    return VaultStorage()


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _resolve_vault(storage: VaultStorage, name_or_id: str):
    """Return vault dict or exit with error."""
    v = storage.find_vault_by_name(name_or_id) or storage.get_vault(name_or_id)
    if not v:
        click.echo(f"Error: vault '{name_or_id}' not found.", err=True)
        sys.exit(1)
    return v


@click.group()
@click.version_option(package_name="loredocs", prog_name="loredocs-cli")
def cli():
    """LoreDocs -- manage your knowledge vaults from the command line."""
    pass


# ---------------------------------------------------------------------------
# vault subgroup
# ---------------------------------------------------------------------------

@cli.group()
def vault():
    """Create and manage vaults."""
    pass


@vault.command(name="list")
@click.option("--all", "include_archived", is_flag=True, help="Include archived vaults.")
def vault_list(include_archived):
    """List all vaults."""
    storage = _storage()
    vaults = storage.list_vaults(include_archived=include_archived)
    if not vaults:
        click.echo("No vaults found.")
        return
    for v in vaults:
        status = " [archived]" if v.get("archived") else ""
        tags = v.get("tags") or []
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        click.echo(f"  {v['name']}{status}  ({v['id']}){tag_str}")
        click.echo(f"    {v.get('doc_count', 0)} docs | {_fmt_size(v.get('total_size_bytes', 0))} | updated {str(v.get('updated_at', ''))[:10]}")


@vault.command(name="create")
@click.argument("name")
@click.option("--desc", default="", help="Description.")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable).")
@click.option("--project", "projects", multiple=True, help="Link project (repeatable).")
def vault_create(name, desc, tags, projects):
    """Create a new vault."""
    storage = _storage()
    result = storage.create_vault(
        name, description=desc,
        tags=list(tags),
        linked_projects=list(projects),
    )
    click.echo(f"Created vault '{result['name']}'  ({result['id']})")


@vault.command(name="info")
@click.argument("name_or_id")
def vault_info(name_or_id):
    """Show vault details and document list."""
    storage = _storage()
    v = _resolve_vault(storage, name_or_id)
    click.echo(f"# {v['name']}  ({v['id']})")
    if v.get("description"):
        click.echo(f"  {v['description']}")
    tags = v.get("tags") or []
    if tags:
        click.echo(f"  Tags: {', '.join(tags)}")
    projects = v.get("linked_projects") or []
    if projects:
        click.echo(f"  Projects: {', '.join(projects)}")
    click.echo(f"  {v.get('doc_count', 0)} docs | {_fmt_size(v.get('total_size_bytes', 0))}")
    click.echo(f"  Updated: {str(v.get('updated_at', ''))[:10]}")

    from .storage import VaultStorage as _VS
    docs = storage.list_documents(v["id"])
    if docs:
        click.echo(f"\n  Documents ({len(docs)}):")
        for d in docs:
            dtags = d.get("tags") or []
            tag_str = f" [{', '.join(dtags)}]" if dtags else ""
            click.echo(f"    {d['name']}  ({d['id']}){tag_str}")
            click.echo(f"      {d.get('category', 'general')} | {d.get('priority', 'normal')} | {_fmt_size(d.get('file_size_bytes', 0))}")


@vault.command(name="archive")
@click.argument("name_or_id")
def vault_archive(name_or_id):
    """Archive a vault (soft delete, restorable)."""
    storage = _storage()
    v = _resolve_vault(storage, name_or_id)
    storage.archive_vault(v["id"])
    click.echo(f"Archived vault '{v['name']}'.")


@vault.command(name="restore")
@click.argument("name_or_id")
def vault_restore(name_or_id):
    """Restore an archived vault."""
    storage = _storage()
    # archived vaults not returned by find_vault_by_name; query by id or name directly
    import sqlite3
    with storage._db() as conn:
        row = conn.execute(
            "SELECT * FROM vaults WHERE LOWER(name)=LOWER(?) OR id=?",
            (name_or_id, name_or_id)
        ).fetchone()
    if not row:
        click.echo(f"Error: vault '{name_or_id}' not found.", err=True)
        sys.exit(1)
    if not row["archived"]:
        click.echo(f"Vault '{row['name']}' is not archived.")
        return
    import sqlite3 as _s
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with storage._db() as conn:
        conn.execute("UPDATE vaults SET archived=0, updated_at=? WHERE id=?", (now, row["id"]))
    click.echo(f"Restored vault '{row['name']}'.")


# ---------------------------------------------------------------------------
# doc subgroup
# ---------------------------------------------------------------------------

@cli.group()
def doc():
    """Add, update, and delete documents."""
    pass


@doc.command(name="add")
@click.argument("vault_name")
@click.argument("doc_name")
@click.option("--file", "file_path", type=click.Path(exists=True), help="File to add.")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read content from stdin.")
@click.option("--category", default="general", help="Category (default: general).")
@click.option("--priority", default="normal", help="Priority (default: normal).")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable).")
@click.option("--notes", default="", help="Notes.")
def doc_add(vault_name, doc_name, file_path, from_stdin, category, priority, tags, notes):
    """Add a document to VAULT_NAME named DOC_NAME."""
    storage = _storage()
    v = _resolve_vault(storage, vault_name)

    if from_stdin:
        content = sys.stdin.buffer.read()
        text = content.decode("utf-8", errors="replace")
        result = storage.add_document_from_text(
            v["id"], doc_name, text,
            tags=list(tags), category=category, priority=priority, notes=notes,
        )
    elif file_path:
        content = Path(file_path).read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")
        result = storage.add_document(
            v["id"], doc_name, content, Path(file_path).name,
            tags=list(tags), category=category, priority=priority, notes=notes,
        )
    else:
        click.echo("Error: provide --file or --stdin.", err=True)
        sys.exit(1)

    if result:
        click.echo(f"Added '{doc_name}'  ({result['id']}) to vault '{v['name']}'")
    else:
        click.echo("Error: failed to add document.", err=True)
        sys.exit(1)


@doc.command(name="update")
@click.argument("doc_id")
@click.option("--name", default=None, help="New document name.")
@click.option("--file", "file_path", type=click.Path(exists=True), help="New content file.")
@click.option("--category", default=None, help="New category.")
@click.option("--priority", default=None, help="New priority.")
@click.option("--tag", "tags", multiple=True, help="Replace tags (repeatable; omit to keep existing).")
@click.option("--notes", default=None, help="New notes.")
def doc_update(doc_id, name, file_path, category, priority, tags, notes):
    """Update document DOC_ID metadata or content."""
    storage = _storage()
    content = None
    filename = None
    if file_path:
        content = Path(file_path).read_bytes()
        filename = Path(file_path).name

    result = storage.update_document(
        doc_id,
        content=content,
        filename=filename,
        name=name,
        tags=list(tags) if tags else None,
        category=category,
        priority=priority,
        notes=notes,
    )
    if result is None:
        click.echo(f"Error: document '{doc_id}' not found.", err=True)
        sys.exit(1)
    click.echo(f"Updated '{result['name']}'  ({doc_id})")


@doc.command(name="delete")
@click.argument("doc_id")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def doc_delete(doc_id, yes):
    """Delete (soft-delete) document DOC_ID."""
    if not yes:
        click.confirm(f"Delete document '{doc_id}'?", abort=True)
    storage = _storage()
    ok = storage.remove_document(doc_id)
    if ok:
        click.echo(f"Deleted document '{doc_id}'.")
    else:
        click.echo(f"Error: document '{doc_id}' not found.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------

@cli.command(name="search")
@click.argument("query")
@click.option("--vault", "vault_name", default=None, help="Limit to a specific vault.")
@click.option("--limit", default=10, show_default=True, help="Max results.")
def search(query, vault_name, limit):
    """Search documents by keyword."""
    storage = _storage()
    vault_id = None
    if vault_name:
        v = _resolve_vault(storage, vault_name)
        vault_id = v["id"]

    results = storage.search(query, vault_id=vault_id, limit=limit)
    if not results:
        click.echo(f"No results for '{query}'.")
        return
    for d in results:
        dtags = d.get("tags") or []
        tag_str = f" [{', '.join(dtags)}]" if dtags else ""
        click.echo(f"  {d['name']}  ({d['id']}){tag_str}")
        click.echo(f"    Vault: {d.get('vault_name', '')} | {d.get('category', '')} | updated {str(d.get('updated_at', ''))[:10]}")


@cli.command(name="ui")
@click.option("--port", default=8766, type=int, show_default=True, help="Port to serve UI on.")
@click.option("--no-browser", is_flag=True, help="Do not open browser automatically.")
@click.option("--no-token-warning", is_flag=True, help="Suppress Pro vault startup warning.")
def ui(port, no_browser, no_token_warning):
    """Start the LoreDocs web UI (requires loredocs[ui] extra)."""
    import os
    from .server import run_ui
    token = os.environ.get("LOREDOCS_UI_TOKEN")
    run_ui(port=port, open_browser=not no_browser, token=token, suppress_warning=no_token_warning)


# ---------------------------------------------------------------------------
# Notion import subcommands (SH-13222: PART:interfaces)
# ---------------------------------------------------------------------------

@cli.group()
def import_():
    """Import from external sources."""
    pass


@import_.command(name="notion")
@click.option("--vault", required=True, help="Vault ID or name to import into.")
@click.option("--page-id", "page_ids", multiple=True, help="Notion page UUID (repeatable).")
@click.option("--database-id", "database_ids", multiple=True, help="Notion database UUID (repeatable).")
@click.option("--tag", "tags", multiple=True, help="Additional tags (repeatable).")
@click.option("--category", default="reference", help="LoreDocs category (default: reference).")
@click.option("--checkpoint-file", default=None, help="Path for resume state (default: env or ~/.loredocs/notion_checkpoint.json).")
@click.option("--resume", is_flag=True, help="Skip pages already in checkpoint.")
def import_notion(vault, page_ids, database_ids, tags, category, checkpoint_file, resume):
    """Import Notion pages and databases into a LoreDocs vault.

    Reads NOTION_TOKEN from environment or keychain. No --max-pages limit
    (CLI has no MCP timeout).

    Exit codes: 0=all pages processed, 1=partial (some errors), 2=fatal (no pages processed).
    """
    import json as _json
    import os as _os
    import signal as _signal
    import sys as _sys
    import time as _time
    import uuid as _uuid
    from datetime import datetime, timezone

    from .notion_import import (
        NotionImporter, NotionTokenMissingError, NotionAPIError,
        NotionImportError, VaultNotFoundError, VaultAmbiguousError,
        WorkspaceSaturationError, CheckpointManager, _resolve_vault,
        _validate_notion_ids, _make_signal_handler, SATURATION_SLEEP_INTERVAL,
        SATURATION_PAUSE_CYCLES, MAX_SATURATION_PAUSES,
    )
    from .notion_checkpoint import redact_secrets

    # Validate at least one ID source
    if not page_ids and not database_ids:
        click.echo("Error: at least one --page-id or --database-id is required.", err=True)
        _sys.exit(2)

    storage = _storage()

    # Resolve vault
    try:
        resolved_vault = _resolve_vault(storage, vault)
    except (VaultNotFoundError, VaultAmbiguousError) as exc:
        click.echo(f"Error: {exc}", err=True)
        _sys.exit(2)

    # Validate Notion UUIDs
    try:
        _validate_notion_ids(list(page_ids), "page_ids")
        _validate_notion_ids(list(database_ids), "database_ids")
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        _sys.exit(2)

    # Resolve checkpoint file
    ckpt_path = checkpoint_file or _os.environ.get(
        "LOREDOCS_NOTION_CHECKPOINT",
        _os.path.expanduser("~/.loredocs/notion_checkpoint.json"),
    )

    ckpt_mgr = CheckpointManager(ckpt_path)
    checkpoint_data = ckpt_mgr.load() if resume else {
        "schema_version": 1,
        "run_id": str(_uuid.uuid4()),
        "entries": {},
    }
    checkpoint_ref = [checkpoint_data]  # mutable container for signal handler

    # Install signal handler for SIGTERM/SIGINT
    handler = _make_signal_handler(ckpt_mgr, checkpoint_ref)
    _signal.signal(_signal.SIGTERM, handler)
    _signal.signal(_signal.SIGINT, handler)

    # Create importer
    try:
        importer = NotionImporter(storage, resolved_vault.id)
    except NotionTokenMissingError as exc:
        click.echo(f"Error: {exc}", err=True)
        _sys.exit(2)

    all_imported = 0
    all_skipped = 0
    all_errors = []
    all_truncated = []
    saturation_pauses = 0

    try:
        # Import database pages
        for db_id in database_ids:
            try:
                db_result = importer.import_database(
                    db_id, tags=list(tags), category=category,
                    checkpoint_data=checkpoint_ref[0],
                )
                all_imported += db_result["imported"]
                all_skipped += db_result["skipped"]
                all_errors.extend(db_result["errors"])
                all_truncated.extend(db_result["truncated_pages"])
            except WorkspaceSaturationError as exc:
                all_errors.append(str(exc))
                saturation_pauses += 1
                if saturation_pauses >= MAX_SATURATION_PAUSES:
                    click.echo(
                        f"Error: {MAX_SATURATION_PAUSES} saturation pauses reached. Aborting.",
                        err=True,
                    )
                    break
                click.echo(
                    f"Workspace saturated. Pausing 5 minutes (pause {saturation_pauses}/{MAX_SATURATION_PAUSES})...",
                    err=True,
                )
                for _ in range(SATURATION_PAUSE_CYCLES):
                    _time.sleep(SATURATION_SLEEP_INTERVAL)

        # Import explicit page IDs
        if page_ids:
            page_result = importer.import_pages(
                list(page_ids), tags=list(tags), category=category,
                checkpoint_data=checkpoint_ref[0],
            )
            all_imported += page_result["imported"]
            all_skipped += page_result["skipped"]
            all_errors.extend(page_result["errors"])
            all_truncated.extend(page_result["truncated_pages"])

        # Save checkpoint
        ckpt_mgr.save(checkpoint_ref[0])

    except WorkspaceSaturationError as exc:
        all_errors.append(str(exc))
        ckpt_mgr.save(checkpoint_ref[0])

    # Print summary
    click.echo(f"Imported: {all_imported}")
    click.echo(f"Skipped (already imported): {all_skipped}")
    if all_errors:
        click.echo(f"Errors: {len(all_errors)}", err=True)
        for err in all_errors:
            click.echo(f"  {err}", err=True)
    if all_truncated:
        click.echo(
            f"Truncated pages (block depth cap): {len(all_truncated)}",
            err=True,
        )
        for pid in all_truncated:
            click.echo(f"  {pid}", err=True)

    # Exit code
    if all_imported == 0 and all_skipped == 0 and all_errors:
        _sys.exit(2)  # fatal: no pages processed
    elif all_errors:
        _sys.exit(1)  # partial: some errors
    else:
        _sys.exit(0)  # all pages processed


@cli.command(name="set-notion-token")
@click.argument("token")
def set_notion_token(token):
    """Store NOTION_TOKEN in the OS keychain."""
    try:
        import keyring
        keyring.set_password("loredocs", "notion_token", token)
        click.echo("Notion token stored in OS keychain.")
    except ImportError:
        click.echo("Error: keyring package not installed. Run: pip install 'loredocs[notion]'", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command(name="clear-notion-token")
def clear_notion_token():
    """Remove NOTION_TOKEN from the OS keychain."""
    try:
        import keyring
        keyring.delete_password("loredocs", "notion_token")
        click.echo("Notion token removed from OS keychain.")
    except ImportError:
        click.echo("Error: keyring package not installed.", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command(name="check-notion")
@click.option("--runtime", is_flag=True, help="Show MCP server interpreter context.")
def check_notion(runtime):
    """Check Notion import readiness and display diagnostic info."""
    import sys as _sys
    import importlib

    python = _sys.executable

    if runtime:
        click.echo(f"[INFO] MCP server Python: {python}")
        click.echo(f"[INFO] Python version: {_sys.version.split()[0]}")

    # Check notion-client
    try:
        importlib.import_module("notion_client")
        click.echo(f"[OK]  notion-client: installed")
    except ImportError:
        click.echo(f"[MISSING] notion-client: not installed")
        click.echo(f"[MISSING] Run: pip install \"loredocs[notion]\"")

    # Check keyring
    try:
        importlib.import_module("keyring")
        click.echo(f"[OK]  keyring: installed")
    except ImportError:
        click.echo(f"[MISSING] keyring: not installed")

    # Recommend uvx
    import shutil
    uv_path = shutil.which("uv")
    if uv_path:
        click.echo(f"[OK]  uv found at {uv_path}")
        click.echo(f"[INFO] Recommended: uvx --with loredocs[notion] loredocs-mcp")
        click.echo(f"[INFO] Launches an isolated environment; durable across restarts.")

    if not runtime:
        click.echo(f"[INFO] Or via uvx: uvx --with loredocs[notion] loredocs-mcp")


@cli.group()
def license():
    """Manage LoreDocs Pro license."""
    pass


@license.command(name="clear")
@click.option("--suite", is_flag=True, default=False,
              help="Also clear suite-wide Pro from sibling product")
def license_clear(suite):
    """Clear the LoreDocs Pro license (and optionally the sibling product's suite key).

    Re-run with --suite to clear suite-wide Pro from both products.
    """
    from loredocs import license_store

    try:
        warnings = license_store.clear_key("loredocs", suite_too=suite)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    if not warnings:
        click.echo("Cleared.")
    else:
        for warning in warnings:
            click.echo(warning)


if __name__ == "__main__":
    cli()
