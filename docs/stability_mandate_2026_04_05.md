# Product Stability Mandate - 2026-04-05

Set by Debbie. Supersedes all previous priority ordering in Ron TODOs.

## Decision

Full feature freeze in effect for LoreConvo and LoreDocs. Ron's only work
is fixing the three action items below until Cowork is confirmed working.

## Current State

- Claude Code CLI: WORKING. settings.json has correct mcpServers + env blocks
  with Pro license keys. MCP tools load and are callable in Code sessions.
- Cowork: BROKEN. Cowork loads MCP servers via plugin system (.plugin files)
  only -- not via settings.json. LoreConvo/LoreDocs MCP tools are not available
  in any Cowork session until the plugin install flow is fixed.

## Ron Action Items (in order, no other work until done)

1. Fix .plugin install flow end-to-end
   - Reproduce the exact failure (error, platform, step)
   - Root-cause: config, transport, server startup, path, .mcp.json, plugin.json
   - Fix so `plugin install loreconvo` and `plugin install loredocs` succeed
   - Verify on Cowork AND Claude Code
   - Document confirmed working install path in INSTALL.md

2. Wire up get_tier as @mcp.tool() in both LoreConvo and LoreDocs server.py
   - get_license_status() already exists in each product's license.py
   - Required so Debbie can verify Pro keys are loading once install works

3. Build scripts/install_dev_plugins.sh
   - Install both .plugin files locally with LAB_DEV_MODE=1 + non-empty *_PRO
   - Lets Debbie run her own products in Cowork without real keys in tracked files

## Definition of Done

Debbie can install LoreConvo AND LoreDocs as plugins in Cowork, MCP tools are
callable in Cowork sessions, sessions persist and are retrievable.
Code is already working -- Cowork is the bar.

## What Is FROZEN

Everything else: marketplace/plugin distribution, CLI interface, developer polish,
new products (Financial Report Generator, CSV Transformer, SQL Optimizer).
Do not touch until mandate is resolved and Debbie confirms.
