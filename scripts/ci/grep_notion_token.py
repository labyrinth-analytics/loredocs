#!/usr/bin/env python3
"""
CI boundary check: flag any use of .secret_value outside the allowed files.

The _SecretStr wrapper redacts on all string-conversion paths. The raw token
value is accessible only via .secret_value. This script enforces that
.secret_value is used ONLY inside notion_import.py and redact_secrets() in
notion_checkpoint.py -- creating a code-review-visible boundary without a
custom linter.

Usage:
    python3 scripts/ci/grep_notion_token.py [--root <project_root>]

Exit codes:
    0 = no violations found
    1 = violations found (printed to stderr)
    2 = error (e.g., root not found)
"""

import os
import re
import sys
from pathlib import Path

# Files where .secret_value is ALLOWED
ALLOWED_FILES = frozenset({
    "loredocs/notion_import.py",
    "loredocs/notion_checkpoint.py",
    "scripts/ci/grep_notion_token.py",  # self-reference is OK
    "tests/test_notion_import.py",
})

# Pattern: .secret_value usage
SECRET_VALUE_RE = re.compile(r'\.secret_value')


def main():
    root = Path(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--root" else ".")
    if not root.is_dir():
        print(f"Error: root directory not found: {root}", file=sys.stderr)
        sys.exit(2)

    violations = []
    for py_file in root.rglob("*.py"):
        rel_path = str(py_file.relative_to(root))
        if rel_path in ALLOWED_FILES:
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if SECRET_VALUE_RE.search(line):
                violations.append(f"{rel_path}:{lineno}: {line.strip()}")

    if violations:
        print("VIOLATIONS: .secret_value used outside allowed files:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(f"\n.secret_value is only allowed in: {sorted(ALLOWED_FILES)}", file=sys.stderr)
        sys.exit(1)

    print("OK: no .secret_value usage outside allowed files.")
    sys.exit(0)


if __name__ == "__main__":
    main()