"""FTS5 query sanitization -- stdlib-only, single source of truth.

Imports nothing outside the stdlib so the fallback script in scripts/ can
load it by file path without installing the package or pulling in storage's
dependencies.

Raw user input must never reach a MATCH clause. FTS5 parses bare hyphens
and colons as query syntax, so a ticket ref like "SH-100406" raises
OperationalError: no such column: 100406.

Both consumers import from here:
  - loredocs/storage.py (LoreDocsStorage._sanitize_fts_query)
  - scripts/query_loredocs.py (fallback CLI)
"""


def sanitize_fts_query(query: str) -> str:
    """OPP-010: Sanitize user input for FTS5 MATCH without changing search semantics.

    Strategy: quote each individual token so hyphens, colons, and other
    FTS5 operators inside a token are treated as literals, but multiple
    tokens are implicitly ANDed (the FTS5 default). This preserves the
    expected behavior where "data warehouse migration" matches documents
    containing all three words anywhere, not just as a consecutive phrase.
    """
    safe = query.strip()
    if not safe:
        return '""'
    tokens = safe.split()
    quoted = ['"' + t.replace('"', '') + '"' for t in tokens if t.replace('"', '')]
    return ' '.join(quoted) if quoted else '""'
