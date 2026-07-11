"""LoreDocs read-only web UI.

Requires loredocs[ui] optional extras:
    pip install loredocs[ui]

Launch via:
    loredocs-cli ui [--port 8766] [--no-browser]
"""

import hmac
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from .storage import DEFAULT_ROOT, DB_FILE
from .tiers import get_tier, TIER_PRO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Document rendering constants (XSS defence layer -- do not loosen)
# ---------------------------------------------------------------------------

ALLOWED_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "code", "pre", "blockquote",
    "a", "strong", "em",
    "table", "tr", "td", "th",
    "del", "s",
})
# Only href is allowed on <a>; all on* handlers are structurally excluded.
ALLOWED_ATTRS = {"a": {"href"}}
SAFE_MD_EXTRAS = ["fenced-code-blocks", "tables", "strike"]

# ---------------------------------------------------------------------------
# Schema validation constants
# ---------------------------------------------------------------------------

REQUIRED_TABLES = {"vaults", "documents"}
OPTIONAL_FTS_TABLE = "doc_fts"

REQUIRED_VAULT_COLUMNS = {"id", "name", "description", "archived", "tags"}
REQUIRED_DOC_COLUMNS = {"id", "vault_id", "name", "deleted", "tags", "category"}

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _resolve_db_path() -> Path:
    root_override = os.environ.get("LOREDOCS_ROOT")
    root = Path(root_override) if root_override else DEFAULT_ROOT
    return root / DB_FILE


def _open_ro(db_path: Path) -> sqlite3.Connection:
    """Open a read-only per-request SQLite connection using Path.as_uri()."""
    try:
        uri = f"{db_path.as_uri()}?mode=ro"
    except ValueError as exc:
        raise ValueError(
            "Cannot open LoreDocs DB: UNC/network paths are not supported. "
            f"Set LOREDOCS_ROOT to a local absolute path. ({exc})"
        )
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=2000")
    return conn


# ---------------------------------------------------------------------------
# FTS sanitization (same logic as VaultStorage._sanitize_fts_query)
# ---------------------------------------------------------------------------


def _sanitize_fts_query(query: str) -> str:
    safe = query.strip()
    if not safe:
        return '""'
    tokens = safe.split()
    quoted = ['"' + t.replace('"', "") + '"' for t in tokens if t.replace('"', "")]
    return " ".join(quoted) if quoted else '""'


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


def _check_ui_imports() -> list:
    import importlib.util
    required = ("fastapi", "uvicorn", "jinja2", "nh3", "markdown2")
    return [pkg for pkg in required if importlib.util.find_spec(pkg) is None]


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def _validate_schema(conn: sqlite3.Connection) -> Optional[str]:
    """Return an error string if the DB schema is too old, else None."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for t in REQUIRED_TABLES:
        if t not in tables:
            return (
                f"Database out of date -- required table missing: {t}. "
                f"Run `loredocs migrate` to update."
            )
    vault_cols = {row[1] for row in conn.execute("PRAGMA table_info(vaults)")}
    for col in REQUIRED_VAULT_COLUMNS:
        if col not in vault_cols:
            return (
                f"Database out of date -- required column missing: {col} in table vaults. "
                f"Run `loredocs migrate` to update."
            )
    doc_cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    for col in REQUIRED_DOC_COLUMNS:
        if col not in doc_cols:
            return (
                f"Database out of date -- required column missing: {col} in table documents. "
                f"Run `loredocs migrate` to update."
            )
    return None


# ---------------------------------------------------------------------------
# run_ui -- main entry point called from CLI
# ---------------------------------------------------------------------------


def run_ui(
    port: int,
    open_browser: bool,
    token: Optional[str] = None,
    suppress_warning: bool = False,
    port_file: Optional[str] = None,
    check_only: bool = False,
) -> None:
    """Start the LoreDocs read-only web UI.

    Raises SystemExit with:
      0 -- normal exit or --check passed all checks
      1 -- startup error (missing extras, bad args, port in use)
      2 -- schema version unsupported (run loredocs migrate)
      3 -- DB missing or unreadable
    """
    # --- LOREDOCS_UI_ENABLED guard ---
    if os.environ.get("LOREDOCS_UI_ENABLED", "1") == "0":
        print("loredocs web UI is disabled (LOREDOCS_UI_ENABLED=0).")
        raise SystemExit(0)

    # --- --check flag: version + import check, no server start ---
    if check_only:
        import importlib.metadata
        try:
            version = importlib.metadata.version("loredocs")
        except Exception:
            version = "unknown"
        print(f"loredocs {version}")
        missing = _check_ui_imports()
        if missing:
            print(f"Missing UI packages: {', '.join(missing)}")
            print("Run: pip install loredocs[ui]")
            raise SystemExit(1)
        print("[OK] UI extras installed.")
        raise SystemExit(0)

    # --- UI extras import guard ---
    missing = _check_ui_imports()
    if missing:
        print(
            f"loredocs[ui] extras are not installed (missing: {', '.join(missing)}). Run:"
        )
        print("  pip install loredocs[ui]")
        raise SystemExit(1)

    # Import after guard -- these only run when extras are present.
    import socket

    from fastapi import Depends, FastAPI, Request, Response
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    db_path = _resolve_db_path()

    # --- Startup warning banner (before any DB access) ---
    sys.stderr.write(
        "WARNING: LoreDocs web UI is running on localhost. Any local process can reach this\n"
        "server. LOREDOCS_UI_TOKEN is strongly recommended if your vaults contain sensitive\n"
        "content. Set: LOREDOCS_UI_TOKEN=$(openssl rand -hex 16) loredocs-cli ui\n"
        "WARNING: Do not run `loredocs-cli ui` inside an SSH tunnel, WSL2, or shared VM "
        "without TLS.\n"
    )

    # --- Try-connect-first approach (avoids TOCTOU of existence-check-then-open) ---
    try:
        startup_conn = _open_ro(db_path)
    except ValueError as exc:
        # UNC/network path unsupported
        print(str(exc), file=sys.stderr)
        raise SystemExit(3)
    except sqlite3.OperationalError:
        if not db_path.exists():
            print(
                "ERROR: No LoreDocs database found. "
                "Run `loredocs migrate` or save your first document via MCP or CLI to initialize.",
                file=sys.stderr,
            )
        elif not os.access(str(db_path), os.R_OK):
            print(
                "ERROR: Permission denied reading LoreDocs database. "
                "Check file permissions.",
                file=sys.stderr,
            )
        else:
            print("ERROR: LoreDocs database error. Check that the file is a valid SQLite DB.",
                  file=sys.stderr)
        raise SystemExit(3)

    # --- Schema validation (exit-before-bind on failure) ---
    schema_error = _validate_schema(startup_conn)
    if schema_error:
        startup_conn.close()
        print(f"ERROR: {schema_error}", file=sys.stderr)
        raise SystemExit(2)

    # --- WAL mode check ---
    row = startup_conn.execute("PRAGMA journal_mode").fetchone()
    if row and row[0] != "wal":
        sys.stderr.write(
            "WARNING: LoreDocs DB is not in WAL mode; concurrent access may cause "
            "'database is locked' errors under write load. "
            "Run `PRAGMA journal_mode=WAL;` to enable.\n"
        )

    # --- FTS availability check ---
    all_tbl = {
        r[0]
        for r in startup_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    has_fts = OPTIONAL_FTS_TABLE in all_tbl

    # --- Pro vault startup warning ---
    if not token and not suppress_warning:
        try:
            vault_count = startup_conn.execute(
                "SELECT COUNT(*) FROM vaults WHERE archived=0"
            ).fetchone()[0]
            if vault_count > 0:
                user_tier = get_tier(db_path.parent)
                if user_tier == TIER_PRO:
                    sys.stderr.write(
                        f"WARNING: {vault_count} Pro vault(s) detected. "
                        "Set LOREDOCS_UI_TOKEN=<token> for additional local-process protection. "
                        "Example: LOREDOCS_UI_TOKEN=$(openssl rand -hex 16) loredocs-cli ui\n"
                    )
        except Exception:
            pass

    startup_conn.close()

    # --- Pre-check port availability before binding uvicorn ---
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_sock.bind(("127.0.0.1", port))
        test_sock.close()
    except OSError:
        print(
            f"ERROR: Port {port} is in use. "
            f"Specify a different port with `loredocs-cli ui --port N`.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # --- Build FastAPI application ---
    templates_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(templates_dir))
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Middleware: CSP (CRITICAL-2 fix: frame-ancestors 'none' added explicitly) ---
    @app.middleware("http")
    async def _csp_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'self'; "
            "img-src 'self'; "
            "font-src 'self'; "
            "script-src 'none'; "
            "frame-ancestors 'none'"
        )
        return response

    # --- Middleware: Cache-Control ---
    @app.middleware("http")
    async def _no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache"
        response.headers["Pragma"] = "no-cache"
        return response

    # --- Middleware: Bearer token auth (per-request env read for hot-reload) ---
    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        if request.url.path == "/api/health":
            return await call_next(request)
        expected = os.environ.get("LOREDOCS_UI_TOKEN", "")
        if expected:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                logger.warning(
                    "LoreDocs UI: failed auth attempt from %s",
                    getattr(request.client, "host", "unknown"),
                )
                return Response(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            provided = auth_header[len("Bearer "):]
            if not hmac.compare_digest(provided, expected):
                logger.warning(
                    "LoreDocs UI: failed auth attempt from %s",
                    getattr(request.client, "host", "unknown"),
                )
                return Response(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    # --- DB exception handler: locked DB returns 503 ---
    @app.exception_handler(sqlite3.OperationalError)
    async def _db_error_handler(request: Request, exc: sqlite3.OperationalError):
        if "locked" in str(exc).lower():
            return Response(
                "Service Unavailable: database temporarily locked",
                status_code=503,
                headers={"Retry-After": "1"},
            )
        logger.error("DB error on %s: %s", request.url.path, exc)
        return Response("Database error", status_code=500)

    # --- Per-request DB connection factory ---
    def _get_db():
        conn = _open_ro(db_path)
        try:
            yield conn
        finally:
            conn.close()

    # --- Routes ---

    @app.get("/", response_class=HTMLResponse)
    async def route_vault_list(request: Request, conn=Depends(_get_db)):
        rows = conn.execute(
            "SELECT id, name, description, tags FROM vaults "
            "WHERE archived=0 ORDER BY name"
        ).fetchall()
        vaults = []
        for r in rows:
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE vault_id=? AND deleted=0",
                (r["id"],),
            ).fetchone()[0]
            vaults.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"] or "",
                    "doc_count": doc_count,
                }
            )
        return templates.TemplateResponse(
            "vault_list.html",
            {"request": request, "vaults": vaults, "has_fts": has_fts},
        )

    @app.get("/vault/{vault_id}", response_class=HTMLResponse)
    async def route_doc_list(vault_id: str, request: Request, conn=Depends(_get_db)):
        vault_row = conn.execute(
            "SELECT id, name, description FROM vaults WHERE id=? AND archived=0",
            (vault_id,),
        ).fetchone()
        if not vault_row:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Vault not found."},
                status_code=404,
            )
        docs = conn.execute(
            "SELECT id, name, category, updated_at FROM documents "
            "WHERE vault_id=? AND deleted=0 ORDER BY updated_at DESC",
            (vault_row["id"],),
        ).fetchall()
        return templates.TemplateResponse(
            "doc_list.html",
            {
                "request": request,
                "vault": {
                    "id": vault_row["id"],
                    "name": vault_row["name"],
                    "description": vault_row["description"] or "",
                },
                "docs": [dict(d) for d in docs],
            },
        )

    @app.get("/vault/{vault_id}/doc/{doc_id}", response_class=HTMLResponse)
    async def route_doc_view(
        vault_id: str, doc_id: str, request: Request, conn=Depends(_get_db)
    ):
        # HIGH fix: enforce vault ownership at SQL level (not app layer)
        # Returns 404 regardless -- avoids confirming doc exists in another vault.
        doc_row = conn.execute(
            "SELECT d.id, d.name, d.category, d.updated_at, d.vault_id, v.name as vault_name "
            "FROM documents d JOIN vaults v ON d.vault_id=v.id "
            "WHERE d.id=? AND d.vault_id=? AND d.deleted=0",
            (doc_id, vault_id),
        ).fetchone()
        if not doc_row:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Document not found."},
                status_code=404,
            )

        # Use vault_id/doc_id from trusted DB result (not user URL params) for paths.
        db_root = db_path.parent
        extracted_path = (
            db_root / "vaults" / doc_row["vault_id"] / "docs" / doc_row["id"] / "extracted.txt"
        )
        raw_text = ""
        if extracted_path.exists():
            try:
                raw_text = extracted_path.read_text(encoding="utf-8")
            except OSError:
                raw_text = ""

        # Render: markdown2 -> nh3 -> Jinja2 | safe
        import markdown2
        import nh3

        html = markdown2.markdown(raw_text, extras=SAFE_MD_EXTRAS)
        clean = nh3.clean(
            html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            url_schemes={"http", "https"},
        )

        return templates.TemplateResponse(
            "doc.html",
            {
                "request": request,
                "doc": {
                    "id": doc_row["id"],
                    "name": doc_row["name"],
                    "category": doc_row["category"],
                    "vault_id": doc_row["vault_id"],
                    "vault_name": doc_row["vault_name"],
                    "updated_at": (doc_row["updated_at"] or "")[:10],
                },
                "content": clean,
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    async def route_search(
        request: Request, q: str = "", conn=Depends(_get_db)
    ):
        import html as _html
        results = []
        fts_unavailable = not has_fts
        if q and has_fts:
            safe_q = _sanitize_fts_query(q)
            # Use plain-text sentinels (not HTML) so we can HTML-escape the snippet
            # and then inject <mark> tags safely.
            _MARK_OPEN = "XXMARKXX"
            _MARK_CLOSE = "XX/MARKXX"
            rows = conn.execute(
                "SELECT d.id, d.name, d.vault_id, v.name as vault_name, "
                f"snippet(doc_fts, 3, '{_MARK_OPEN}', '{_MARK_CLOSE}', '...', 32) as snippet "
                "FROM doc_fts "
                "JOIN documents d ON d.id = doc_fts.doc_id "
                "JOIN vaults v ON d.vault_id = v.id "
                "WHERE doc_fts MATCH ? AND d.deleted = 0 "
                "ORDER BY rank LIMIT 50",
                (safe_q,),
            ).fetchall()
            for r in rows:
                raw_snip = r["snippet"] or ""
                # HTML-escape the full snippet (neutralises any <, >, & in doc content)
                escaped = _html.escape(raw_snip)
                # Now inject the <mark> tags (sentinels are plain text -- survive escape)
                safe_snip = escaped.replace(_MARK_OPEN, "<mark>").replace(
                    _MARK_CLOSE, "</mark>"
                )
                results.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "vault_id": r["vault_id"],
                        "vault_name": r["vault_name"],
                        "snippet": safe_snip,
                    }
                )
        elif q and not has_fts:
            fts_unavailable = True

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "q": q,
                "results": results,
                "fts_unavailable": fts_unavailable,
            },
        )

    @app.get("/api/health")
    async def route_health():
        try:
            conn = _open_ro(db_path)
            conn.execute("SELECT 1")
            conn.close()
            db_status = "connected"
        except Exception:
            db_status = "error" if db_path.exists() else "missing"
        return JSONResponse({"status": "ok", "db": db_status})

    # --- Write port file before serving (port is deterministic) ---
    if port_file:
        try:
            Path(port_file).write_text(str(port))
        except OSError as exc:
            print(f"WARNING: could not write port file {port_file}: {exc}", file=sys.stderr)

    # --- Auto-open browser ---
    if open_browser:
        import threading
        import time
        import webbrowser

        def _open_browser():
            time.sleep(0.8)
            webbrowser.open(f"http://127.0.0.1:{port}")

        threading.Thread(target=_open_browser, daemon=True).start()

    # --- Start uvicorn ---
    import uvicorn

    sys.stderr.write(
        f"LoreDocs web UI: http://127.0.0.1:{port} (Ctrl+C to stop)\n"
    )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    server.run()


# ---------------------------------------------------------------------------
# Testable app factory (skips startup validation + uvicorn)
# ---------------------------------------------------------------------------


def _build_app(db_path: Path, has_fts: bool):
    """Create and return the FastAPI app bound to db_path. Used by tests."""
    from fastapi import Depends, FastAPI, Request, Response
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    templates_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(templates_dir))
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.middleware("http")
    async def _csp(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self'; "
            "font-src 'self'; script-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.middleware("http")
    async def _no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        if request.url.path == "/api/health":
            return await call_next(request)
        expected = os.environ.get("LOREDOCS_UI_TOKEN", "")
        if expected:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                logger.warning(
                    "LoreDocs UI: failed auth attempt from %s",
                    getattr(request.client, "host", "unknown"),
                )
                return Response("Unauthorized", status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
            provided = auth_header[len("Bearer "):]
            if not hmac.compare_digest(provided, expected):
                logger.warning(
                    "LoreDocs UI: failed auth attempt from %s",
                    getattr(request.client, "host", "unknown"),
                )
                return Response("Unauthorized", status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)

    @app.exception_handler(sqlite3.OperationalError)
    async def _db_err(request: Request, exc: sqlite3.OperationalError):
        if "locked" in str(exc).lower():
            return Response("Service Unavailable", status_code=503,
                            headers={"Retry-After": "1"})
        return Response("Database error", status_code=500)

    def _get_db():
        if db_path.exists():
            uri = f"{db_path.as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    async def _vault_list(request: Request, conn=Depends(_get_db)):
        rows = conn.execute(
            "SELECT id, name, description FROM vaults WHERE archived=0 ORDER BY name"
        ).fetchall()
        vaults = []
        for r in rows:
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE vault_id=? AND deleted=0",
                (r["id"],),
            ).fetchone()[0]
            vaults.append({"id": r["id"], "name": r["name"],
                           "description": r["description"] or "", "doc_count": doc_count})
        return templates.TemplateResponse(
            "vault_list.html", {"request": request, "vaults": vaults, "has_fts": has_fts}
        )

    @app.get("/vault/{vault_id}", response_class=HTMLResponse)
    async def _doc_list(vault_id: str, request: Request, conn=Depends(_get_db)):
        vault_row = conn.execute(
            "SELECT id, name, description FROM vaults WHERE id=? AND archived=0",
            (vault_id,),
        ).fetchone()
        if not vault_row:
            return templates.TemplateResponse("error.html",
                {"request": request, "message": "Vault not found."}, status_code=404)
        docs = conn.execute(
            "SELECT id, name, category, updated_at FROM documents "
            "WHERE vault_id=? AND deleted=0 ORDER BY updated_at DESC",
            (vault_row["id"],),
        ).fetchall()
        return templates.TemplateResponse("doc_list.html", {
            "request": request,
            "vault": {"id": vault_row["id"], "name": vault_row["name"],
                      "description": vault_row["description"] or ""},
            "docs": [dict(d) for d in docs],
        })

    @app.get("/vault/{vault_id}/doc/{doc_id}", response_class=HTMLResponse)
    async def _doc_view(vault_id: str, doc_id: str, request: Request, conn=Depends(_get_db)):
        doc_row = conn.execute(
            "SELECT d.id, d.name, d.category, d.updated_at, d.vault_id, v.name as vault_name "
            "FROM documents d JOIN vaults v ON d.vault_id=v.id "
            "WHERE d.id=? AND d.vault_id=? AND d.deleted=0",
            (doc_id, vault_id),
        ).fetchone()
        if not doc_row:
            return templates.TemplateResponse("error.html",
                {"request": request, "message": "Document not found."}, status_code=404)
        db_root = db_path.parent
        extracted_path = (
            db_root / "vaults" / doc_row["vault_id"] / "docs" / doc_row["id"] / "extracted.txt"
        )
        raw_text = ""
        if extracted_path.exists():
            try:
                raw_text = extracted_path.read_text(encoding="utf-8")
            except OSError:
                pass
        import markdown2
        import nh3
        html = markdown2.markdown(raw_text, extras=SAFE_MD_EXTRAS)
        clean = nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
                          url_schemes={"http", "https"})
        return templates.TemplateResponse("doc.html", {
            "request": request,
            "doc": {"id": doc_row["id"], "name": doc_row["name"],
                    "category": doc_row["category"], "vault_id": doc_row["vault_id"],
                    "vault_name": doc_row["vault_name"],
                    "updated_at": (doc_row["updated_at"] or "")[:10]},
            "content": clean,
        })

    @app.get("/search", response_class=HTMLResponse)
    async def _search(request: Request, q: str = "", conn=Depends(_get_db)):
        import html as _html
        results = []
        fts_unavailable = not has_fts
        if q and has_fts:
            safe_q = _sanitize_fts_query(q)
            _MO, _MC = "XXMARKXX", "XX/MARKXX"
            rows = conn.execute(
                "SELECT d.id, d.name, d.vault_id, v.name as vault_name, "
                f"snippet(doc_fts, 3, '{_MO}', '{_MC}', '...', 32) as snippet "
                "FROM doc_fts JOIN documents d ON d.id=doc_fts.doc_id "
                "JOIN vaults v ON d.vault_id=v.id "
                "WHERE doc_fts MATCH ? AND d.deleted=0 ORDER BY rank LIMIT 50",
                (safe_q,),
            ).fetchall()
            for r in rows:
                escaped = _html.escape(r["snippet"] or "")
                results.append({"id": r["id"], "name": r["name"],
                                 "vault_id": r["vault_id"], "vault_name": r["vault_name"],
                                 "snippet": escaped.replace(_MO, "<mark>").replace(_MC, "</mark>")})
        elif q:
            fts_unavailable = True
        return templates.TemplateResponse("search.html",
            {"request": request, "q": q, "results": results, "fts_unavailable": fts_unavailable})

    @app.get("/api/health")
    async def _health():
        try:
            c = _open_ro(db_path)
            c.execute("SELECT 1")
            c.close()
            return JSONResponse({"status": "ok", "db": "connected"})
        except Exception:
            return JSONResponse({"status": "ok",
                                 "db": "error" if db_path.exists() else "missing"})

    return app
