#!/bin/bash
# ============================================================
# cleanup_internal_docs.sh
# Run on Mac to finish the internal doc relocation that Cowork
# couldn't complete (file permission limitations).
#
# This script:
#   1. Deletes the original internal docs from product directories
#   2. Commits everything (gitignore, moved docs, CLAUDE.md updates)
#   3. Runs the pre-push verification
#
# USAGE:
#   cd ~/projects/side_hustle
#   bash scripts/cleanup_internal_docs.sh
# ============================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Internal Doc Cleanup ===${NC}"

# Clean any stale lock files first (common Cowork leftover)
find .git -name "*.lock" -delete 2>/dev/null || true

# Delete LoreConvo originals
echo "Removing LoreConvo internal docs from product directory..."
rm -f ron_skills/loreconvo/docs/LoreConvo_Revenue_Projection.xlsx
rm -f ron_skills/loreconvo/docs/ConvoVault_Revenue_Projection.xlsx
rm -f ron_skills/loreconvo/docs/session-bridge-prd.md
rm -f ron_skills/loreconvo/docs/PUBLISHING.md
rm -f ron_skills/loreconvo/docs/marketplace_listing.md
rm -f ron_skills/loreconvo/docs/build_revenue_projection.py

# Delete LoreDocs originals
echo "Removing LoreDocs internal docs from product directory..."
rm -f ron_skills/loredocs/docs/PUBLISHING.md
rm -f ron_skills/loredocs/docs/marketplace_listing.md
rm -f ron_skills/loredocs/docs/LoreDocs_Product_Spec.md
rm -f ron_skills/loredocs/docs/ProjectVault_Product_Spec.md

echo -e "${GREEN}Originals removed.${NC}"

# Verify internal docs are in new location
echo ""
echo "Verifying docs in new locations..."
for f in docs/internal/loreconvo/LoreConvo_Revenue_Projection.xlsx \
         docs/internal/loreconvo/session-bridge-prd.md \
         docs/internal/loreconvo/PUBLISHING.md \
         docs/internal/loredocs/PUBLISHING.md \
         docs/internal/loredocs/LoreDocs_Product_Spec.md; do
    if [ -f "$f" ]; then
        echo -e "  ${GREEN}[OK]${NC} $f"
    else
        echo -e "  ${RED}[MISSING]${NC} $f"
    fi
done

# Stage and commit
echo ""
echo "Staging changes..."
git add docs/internal/
git add ron_skills/loreconvo/.gitignore
git add ron_skills/loredocs/.gitignore
git add CLAUDE.md
git add scripts/scrub_public_repos.sh
git add scripts/verify_public_repo_clean.sh
git add scripts/cleanup_internal_docs.sh

echo "Committing..."
git commit -m "move internal docs out of public product directories

Relocated revenue projections, PRDs, publishing strategies, and
marketplace listings from ron_skills/loreconvo/docs/ and
ron_skills/loredocs/docs/ to docs/internal/ (private monorepo only).
Simplified product .gitignore files to use generic patterns.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

# Run verification
echo ""
bash scripts/verify_public_repo_clean.sh

echo ""
echo -e "${GREEN}=== Done! ===${NC}"
echo "Next steps:"
echo "  1. git push origin master"
echo "  2. git subtree push --prefix=ron_skills/loreconvo loreconvo main"
echo "  3. git subtree push --prefix=ron_skills/loredocs loredocs main"
echo "  4. bash scripts/scrub_public_repos.sh  (to clean git history)"
