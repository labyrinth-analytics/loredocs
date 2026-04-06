#!/bin/bash
# install_dev_plugins.sh -- Developer install of LoreConvo + LoreDocs for Cowork
#
# Purpose: Builds dev copies of both .plugin files that:
#   1. Use the LOCAL source code venv (not uvx -- products aren't on PyPI yet)
#   2. Set LAB_DEV_MODE=1 to bypass license validation
#   3. Include a placeholder *_PRO value so Pro features work
#
# This lets Debbie run her own products in Cowork without:
#   - Publishing to PyPI
#   - Putting real signed license keys into tracked .plugin files
#   - Using the broken uvx path
#
# Usage:
#   bash scripts/install_dev_plugins.sh
#   (Run from the side_hustle repo root)
#
# Output:
#   dev-plugins/loreconvo-dev.plugin
#   dev-plugins/loredocs-dev.plugin
#
# After running, install in Cowork:
#   /plugin install /full/path/to/dev-plugins/loreconvo-dev.plugin
#   /plugin install /full/path/to/dev-plugins/loredocs-dev.plugin
#
# NOTE: dev-plugins/ is gitignored. The .plugin files contain absolute paths
# to your local venv -- not portable, not for distribution.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LORECONVO_SRC="$REPO_ROOT/ron_skills/loreconvo"
LOREDOCS_SRC="$REPO_ROOT/ron_skills/loredocs"
LORECONVO_PLUGIN_DIR="$REPO_ROOT/ron_skills/loreconvo-plugin"
LOREDOCS_PLUGIN_DIR="$REPO_ROOT/ron_skills/loredocs-plugin"
DEV_OUT="$REPO_ROOT/dev-plugins"

echo ""
echo "=== Lore Developer Plugin Installer ==="
echo "Builds dev .plugin files for local Cowork testing."
echo "Repo: $REPO_ROOT"
echo ""

# Validate we're in the right place
if [ ! -d "$LORECONVO_SRC" ] || [ ! -d "$LOREDOCS_SRC" ]; then
    echo "[ERROR] Product source directories not found."
    echo "Run this script from the side_hustle repo root."
    echo "Expected: $LORECONVO_SRC"
    exit 1
fi

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is required. Install via: brew install python3"
    exit 1
fi

# ---------------------------------------------------------------
# Step 1: Set up LoreConvo venv and install from source
# ---------------------------------------------------------------
echo "[1/4] Setting up LoreConvo venv..."
cd "$LORECONVO_SRC"
if [ ! -d ".venv" ]; then
    echo "     Creating .venv..."
    python3 -m venv .venv
fi
.venv/bin/pip install -q -e . 2>&1 | grep -v "^$" | tail -3

LORECONVO_BIN="$LORECONVO_SRC/.venv/bin/loreconvo"
if [ ! -f "$LORECONVO_BIN" ]; then
    echo "[ERROR] loreconvo entry point not found at: $LORECONVO_BIN"
    echo "Check that pyproject.toml [project.scripts] defines 'loreconvo'."
    exit 1
fi
echo "     [OK] loreconvo binary: $LORECONVO_BIN"

# ---------------------------------------------------------------
# Step 2: Set up LoreDocs venv and install from source
# ---------------------------------------------------------------
echo "[2/4] Setting up LoreDocs venv..."
cd "$LOREDOCS_SRC"
if [ ! -d ".venv" ]; then
    echo "     Creating .venv..."
    python3 -m venv .venv
fi
.venv/bin/pip install -q -e . 2>&1 | grep -v "^$" | tail -3

LOREDOCS_BIN="$LOREDOCS_SRC/.venv/bin/loredocs"
if [ ! -f "$LOREDOCS_BIN" ]; then
    echo "[ERROR] loredocs entry point not found at: $LOREDOCS_BIN"
    echo "Check that pyproject.toml [project.scripts] defines 'loredocs'."
    exit 1
fi
echo "     [OK] loredocs binary: $LOREDOCS_BIN"

# ---------------------------------------------------------------
# Step 3: Build dev .plugin files
# Each file is a zip containing:
#   - .mcp.json: modified with local binary + dev env vars
#   - .claude-plugin/plugin.json: unchanged
#   - README.md: unchanged
#   - skills/: all user-facing skills
# ---------------------------------------------------------------
echo "[3/4] Building dev .plugin files..."
mkdir -p "$DEV_OUT"

# Build loreconvo-dev.plugin
python3 - << PYEOF
import zipfile, json, os, sys

plugin_dir = "$LORECONVO_PLUGIN_DIR"
output_path = "$DEV_OUT/loreconvo-dev.plugin"
loreconvo_bin = "$LORECONVO_BIN"

# Read the released .mcp.json as a base
mcp_path = os.path.join(plugin_dir, ".mcp.json")
if not os.path.exists(mcp_path):
    print("[ERROR] .mcp.json not found in loreconvo-plugin/")
    sys.exit(1)

with open(mcp_path) as f:
    mcp = json.load(f)

# Override: use local binary and dev bypass
mcp["mcpServers"]["loreconvo"]["command"] = loreconvo_bin
mcp["mcpServers"]["loreconvo"]["args"] = []
mcp["mcpServers"]["loreconvo"]["env"] = {
    "LAB_DEV_MODE": "1",
    "LORECONVO_PRO": "dev-local",
}

# Build the zip
with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    # Write the modified .mcp.json
    zf.writestr(".mcp.json", json.dumps(mcp, indent=2))
    # Always include plugin.json from .claude-plugin/ (required for Cowork validation)
    plugin_json_path = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    if os.path.exists(plugin_json_path):
        zf.write(plugin_json_path, ".claude-plugin/plugin.json")
    # Add all other files from the plugin directory
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # skip other hidden dirs
        for fname in files:
            if fname in (".DS_Store", ".mcp.json"):
                continue
            full = os.path.join(root, fname)
            arc = os.path.relpath(full, plugin_dir)
            zf.write(full, arc)

# Verify contents
with zipfile.ZipFile(output_path) as zf:
    contents = sorted(zf.namelist())

print("     [OK] loreconvo-dev.plugin")
print("     Contents:")
for c in contents:
    print(f"       {c}")
PYEOF

# Build loredocs-dev.plugin
python3 - << PYEOF
import zipfile, json, os, sys

plugin_dir = "$LOREDOCS_PLUGIN_DIR"
output_path = "$DEV_OUT/loredocs-dev.plugin"
loredocs_bin = "$LOREDOCS_BIN"

# Read the released .mcp.json as a base
mcp_path = os.path.join(plugin_dir, ".mcp.json")
if not os.path.exists(mcp_path):
    print("[ERROR] .mcp.json not found in loredocs-plugin/")
    sys.exit(1)

with open(mcp_path) as f:
    mcp = json.load(f)

# Override: use local binary and dev bypass
mcp["mcpServers"]["loredocs"]["command"] = loredocs_bin
mcp["mcpServers"]["loredocs"]["args"] = []
mcp["mcpServers"]["loredocs"]["env"] = {
    "LAB_DEV_MODE": "1",
    "LOREDOCS_PRO": "dev-local",
}

# Build the zip
with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    # Write the modified .mcp.json
    zf.writestr(".mcp.json", json.dumps(mcp, indent=2))
    # Always include plugin.json from .claude-plugin/ (required for Cowork validation)
    plugin_json_path = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    if os.path.exists(plugin_json_path):
        zf.write(plugin_json_path, ".claude-plugin/plugin.json")
    # Add all other files from the plugin directory
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # skip other hidden dirs
        for fname in files:
            if fname in (".DS_Store", ".mcp.json"):
                continue
            full = os.path.join(root, fname)
            arc = os.path.relpath(full, plugin_dir)
            zf.write(full, arc)

# Verify contents
with zipfile.ZipFile(output_path) as zf:
    contents = sorted(zf.namelist())

print("     [OK] loredocs-dev.plugin")
print("     Contents:")
for c in contents:
    print(f"       {c}")
PYEOF

# ---------------------------------------------------------------
# Step 4: Add dev-plugins/ to .gitignore (if not already there)
# ---------------------------------------------------------------
GITIGNORE="$REPO_ROOT/.gitignore"
if ! grep -q "dev-plugins/" "$GITIGNORE" 2>/dev/null; then
    echo "" >> "$GITIGNORE"
    echo "# Dev plugin builds (contain absolute local paths, not for distribution)" >> "$GITIGNORE"
    echo "dev-plugins/" >> "$GITIGNORE"
    echo "     [OK] Added dev-plugins/ to .gitignore"
fi

echo ""
echo "[4/4] Done!"
echo ""
echo "Dev plugin files:"
ls -lh "$DEV_OUT/"
echo ""
echo "================================================================"
echo " NEXT STEPS: Install in Cowork"
echo "================================================================"
echo ""
echo " In a Cowork conversation, run these two commands:"
echo ""
echo "   /plugin install $DEV_OUT/loreconvo-dev.plugin"
echo "   /plugin install $DEV_OUT/loredocs-dev.plugin"
echo ""
echo " After install, verify in a NEW Cowork session:"
echo "   Ask Claude: 'Call get_tier to verify LoreConvo is connected'"
echo "   Expected:   tier = pro (dev mode)"
echo ""
echo "   Ask Claude: 'Call get_license_tier to verify LoreDocs is connected'"
echo "   Expected:   tier = pro (dev mode)"
echo ""
echo "================================================================"
echo " SECURITY NOTES"
echo "================================================================"
echo " - LAB_DEV_MODE=1 bypasses license key validation"
echo " - LORECONVO_PRO=dev-local / LOREDOCS_PRO=dev-local are placeholders"
echo " - dev-plugins/ is gitignored -- never commit these files"
echo " - .plugin files contain absolute paths to $REPO_ROOT"
echo "   They will NOT work on another machine"
echo "================================================================"
echo ""
