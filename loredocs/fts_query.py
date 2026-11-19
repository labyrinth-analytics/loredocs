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

import re

# A double-quoted phrase (greedy up to the next quote, requires a closing
# quote -- callers only reach here after validate_fts_query has confirmed
# quotes are balanced) optionally followed directly by a prefix '*', or a
# run of non-whitespace characters (a bare token, which may itself end in
# '*' or contain a stray unmatched quote char).
_TOKEN_RE = re.compile(r'"([^"]*)"(\*)?|(\S+)')

# SH-106703: recognize these bare tokens without regard to case. Their
# original spelling is retained unless pass 2 confirms operator placement.
_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})


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

    Strategy: quote each individual bare token so hyphens, colons, and other
    FTS5 operators inside a token are treated as literals, but multiple bare
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

    SH-104947 D-14: a caller-supplied double-quoted phrase ("rental
    income") was silently flattened to the same bare-AND query as the
    unquoted form -- `safe.split()` tokenized on whitespace first, so the
    quote characters landed on the first/last word and were then stripped
    like any other embedded quote. This broke the "Phrases" syntax the
    `vault_search` tool docstring advertises: a phrase query matched
    nothing more precisely than the equivalent bare words, so it could
    never narrow a known-item search among documents that share the same
    vocabulary (e.g. templated reports repeating the same boilerplate
    terms). A quoted segment is now preserved as one FTS5 phrase (true
    consecutive-word matching); bare tokens outside quotes keep the
    existing AND-of-terms behavior unchanged.

    SH-106652: the `vault_search` docstring also advertises the FTS5
    boolean operators ("depreciation AND schedule", "rental NOT
    commercial"), but quote-everything turned them into literal words, so
    'mail OR gmail' required all three words and 'rental NOT commercial'
    required the word "not" and excluded nothing. A bare AND / OR / NOT
    token in any letter case is normalized to uppercase and emitted
    unquoted only when it sits directly between two operands (a quoted
    phrase or a non-operator bare token). A stray operator -- leading, trailing, or
    adjacent to another operator ("OR mail", "mail AND", "a AND OR b",
    "NOT AND OR") -- is quoted as a literal word, so the output always
    parses and never raises OperationalError. Quoted operator words and
    phrases remain literal; normalization applies only to valid operators.
    """
    safe = query.strip()
    if not safe:
        return '""'
    # Pass 1: tokenize into (is_operator, text) pairs, dropping empties.
    # Operands are quoted here; operators are kept bare so pass 2 can
    # decide whether each one is positioned validly.
    tokens = []
    for match in _TOKEN_RE.finditer(safe):
        phrase, phrase_prefix, bare = match.group(1), match.group(2), match.group(3)
        if phrase is not None:
            inner = phrase.replace('"', '').strip()
            if not inner:
                continue
            tokens.append((False, '"' + inner + '"' + ('*' if phrase_prefix else '')))
            continue
        if bare.upper() in _BOOLEAN_OPERATORS:
            tokens.append((True, bare))
            continue
        is_prefix = len(bare) > 1 and bare.endswith('*')
        core = (bare[:-1] if is_prefix else bare).replace('"', '')
        if not core:
            continue
        tokens.append((False, '"' + core + '"*' if is_prefix else '"' + core + '"'))
    if not tokens:
        return '""'
    # Pass 2: an operator is real only when both neighbours are operands.
    # Anything else (edge position, operator next to operator) is literal.
    clauses = []
    last = len(tokens) - 1
    for i, (is_op, text) in enumerate(tokens):
        if not is_op:
            clauses.append(text)
            continue
        has_operand_before = i > 0 and not tokens[i - 1][0]
        has_operand_after = i < last and not tokens[i + 1][0]
        if has_operand_before and has_operand_after:
            clauses.append(text.upper())
        else:
            clauses.append('"' + text + '"')
    return ' '.join(clauses)
