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


def validate_fts_query(query: str) -> str | None:
    """Return an error message if `query` is malformed FTS5 syntax, else None.

    Detects the malformed-input classes that FTS5 would either reject or
    silently mis-parse, before sanitization hides them. WG-32 D-35: a query
    like '"unclosed' (an odd number of double-quote characters) was being
    sanitized into a phrase query and returned results, where a structured
    error is the correct response.

    Checks (each returns an error string naming the problem):
      - Unbalanced double-quotes (odd count of `"`).
      - Unbalanced parentheses (mismatched `(` vs `)`).
    """
    text = query.strip()
    if not text:
        return None

    if text.count('"') % 2 != 0:
        return (
            f"Malformed FTS query: unbalanced double-quote in '{query}'. "
            "Wrap phrases in matching quotes, e.g. '\"rental income\"'."
        )

    if text.count('(') != text.count(')'):
        return (
            f"Malformed FTS query: unbalanced parentheses in '{query}'. "
            "Ensure every '(' has a matching ')'."
        )

    return None


def sanitize_fts_query(query: str) -> str:
    """OPP-010: Sanitize user input for FTS5 MATCH without changing search semantics.

    Strategy: quote each individual token so hyphens, colons, and other
    FTS5 operators inside a token are treated as literals, but multiple
    tokens are implicitly ANDed (the FTS5 default). This preserves the
    expected behavior where "data warehouse migration" matches documents
    containing all three words anywhere, not just as a consecutive phrase.

    SH-104947 D-14b: a trailing '*' is FTS5's prefix-query operator, but
    quoting the whole token (the strategy above) put the '*' INSIDE the
    quotes -- "vaultstor*" is then a literal phrase match for the three
    characters v-a-u-l-t-s-t-o-r-*, which no real document contains, so
    every prefix query returned zero rows while the equivalent full word
    worked fine. FTS5 accepts '*' as a prefix operator immediately after a
    closing quote with no intervening whitespace ("vaultstor"*), so a
    trailing '*' is now split off and re-appended outside the quotes.
    """
    safe = query.strip()
    if not safe:
        return '""'
    tokens = safe.split()
    quoted = []
    for t in tokens:
        is_prefix = len(t) > 1 and t.endswith('*')
        core = (t[:-1] if is_prefix else t).replace('"', '')
        if not core:
            continue
        quoted.append('"' + core + '"*' if is_prefix else '"' + core + '"')
    return ' '.join(quoted) if quoted else '""'
