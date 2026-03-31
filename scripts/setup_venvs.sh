#!/bin/bash
# Setup virtual environments for all products
# Run from the side_hustle root: bash scripts/setup_venvs.sh

set -e

echo "=== Setting up product virtual environments ==="

# SQL Query Optimizer - needs a .venv
if [ ! -d "ron_skills/sql_query_optimizer/.venv" ]; then
    echo "[+] Creating SQL Query Optimizer .venv..."
    python3 -m venv ron_skills/sql_query_optimizer/.venv
    ron_skills/sql_query_optimizer/.venv/bin/pip install --upgrade pip
    ron_skills/sql_query_optimizer/.venv/bin/pip install -r ron_skills/sql_query_optimizer/api/requirements.txt
    echo "[OK] SQL Query Optimizer .venv created"
else
    echo "[OK] SQL Query Optimizer .venv already exists"
fi

# LoreConvo - verify existing .venv
if [ -d "ron_skills/loreconvo/.venv" ]; then
    echo "[OK] LoreConvo .venv exists"
else
    echo "[+] Creating LoreConvo .venv..."
    python3 -m venv ron_skills/loreconvo/.venv
    ron_skills/loreconvo/.venv/bin/pip install --upgrade pip
    ron_skills/loreconvo/.venv/bin/pip install -r ron_skills/loreconvo/requirements-lock.txt
    echo "[OK] LoreConvo .venv created"
fi

# LoreDocs - verify existing .venv
if [ -d "ron_skills/loredocs/.venv" ]; then
    echo "[OK] LoreDocs .venv exists"
else
    echo "[+] Creating LoreDocs .venv..."
    python3 -m venv ron_skills/loredocs/.venv
    ron_skills/loredocs/.venv/bin/pip install --upgrade pip
    ron_skills/loredocs/.venv/bin/pip install -r ron_skills/loredocs/requirements-lock.txt
    echo "[OK] LoreDocs .venv created"
fi

echo ""
echo "=== Running pip-audit on all products ==="

for product in loreconvo loredocs sql_query_optimizer; do
    venv="ron_skills/$product/.venv"
    if [ -d "$venv" ]; then
        echo "--- Auditing $product ---"
        $venv/bin/pip install pip-audit 2>/dev/null
        $venv/bin/pip-audit || echo "[!] $product has vulnerabilities -- review above"
    fi
done

echo ""
echo "=== Done ==="
