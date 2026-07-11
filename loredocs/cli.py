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
@click.option("--port-file", default=None, help="Write bound port as integer to this path.")
@click.option("--check", "check_only", is_flag=True, help="Check UI extras and exit (no server).")
def ui(port, no_browser, no_token_warning, port_file, check_only):
    """Start the LoreDocs web UI (requires loredocs[ui] extra)."""
    import os
    from .server import run_ui
    token = os.environ.get("LOREDOCS_UI_TOKEN")
    run_ui(
        port=port,
        open_browser=not no_browser,
        token=token,
        suppress_warning=no_token_warning,
        port_file=port_file,
        check_only=check_only,
    )


if __name__ == "__main__":
    cli()
