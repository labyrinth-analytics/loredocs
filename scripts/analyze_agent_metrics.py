#!/usr/bin/env python3
"""
Comprehensive Agent Metrics Analyzer - extract performance metrics from ALL agent outputs
"""
import os
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def parse_date_from_filename(filename):
    """Extract YYYY_MM_DD from filename like qa_report_2026_04_04.md"""
    match = re.search(r'(\d{4})_(\d{2})_(\d{2})', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None

def analyze_qa_reports():
    """Analyze Meg's QA reports"""
    qa_dir = Path("docs/internal/qa")
    metrics = {}

    for report_file in sorted(qa_dir.glob("qa_report_*.md")):
        date = parse_date_from_filename(report_file.name)
        if not date:
            continue

        content = report_file.read_text()
        test_match = re.search(r'(\d+)\s+(?:new\s+)?tests?', content, re.IGNORECASE)
        tests = int(test_match.group(1)) if test_match else 0
        severity = "GREEN" if "GREEN" in content else "YELLOW" if "YELLOW" in content else "RED"

        metrics[date] = {'tests': tests, 'severity': severity, 'size_kb': report_file.stat().st_size / 1024}

    return "Meg (QA Engineer)", metrics

def analyze_security_reports():
    """Analyze Brock's security reports"""
    sec_dir = Path("docs/internal/security")
    metrics = {}

    for report_file in sorted(sec_dir.glob("security_report_*.md")):
        date = parse_date_from_filename(report_file.name)
        if not date:
            continue

        content = report_file.read_text()
        severity = "SECURE" if "SECURE" in content else "NEEDS ATTENTION" if "NEEDS ATTENTION" in content else "AT RISK"
        findings = content.count("SEC-")

        metrics[date] = {'findings': findings, 'severity': severity, 'size_kb': report_file.stat().st_size / 1024}

    return "Brock (Cybersecurity Expert)", metrics

def analyze_pm_reports():
    """Analyze Jacqueline's PM reports (daily + weekly separate)"""
    pm_dir = Path("docs/internal/pm")

    daily = {}
    weekly = {}

    for report_file in sorted(pm_dir.glob("executive_dashboard_*.html")):
        date = parse_date_from_filename(report_file.name)
        if date:
            daily[date] = {'type': 'dashboard', 'size_kb': report_file.stat().st_size / 1024}

    for report_file in sorted(pm_dir.glob("labyrinth_product_roadmap_*.html")):
        date = parse_date_from_filename(report_file.name)
        if date:
            weekly[date] = {'type': 'roadmap', 'size_kb': report_file.stat().st_size / 1024}

    return "Jacqueline (Project Manager)", {'daily': daily, 'weekly': weekly}

def analyze_marketing_reports():
    """Analyze Madison's marketing content"""
    marketing_dir = Path("docs/internal/marketing")
    metrics = {}

    blog_dir = marketing_dir / "blog_drafts"
    if blog_dir.exists():
        for blog_file in sorted(blog_dir.glob("*.md")):
            # Try to extract date from filename or content
            content = blog_file.read_text()
            date_match = re.search(r'date:\s*(\d{4})-(\d{2})-(\d{2})', content)
            if date_match:
                date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                metrics[date] = {'type': 'blog_draft', 'size_kb': blog_file.stat().st_size / 1024}

    return "Madison (Marketing Content Creator)", metrics

def analyze_architecture_reports():
    """Analyze Gina's architecture reviews"""
    arch_dir = Path("docs/internal/architecture")
    metrics = {}

    for report_file in sorted(arch_dir.glob("product_review_*.md")):
        date = parse_date_from_filename(report_file.name)
        if date:
            metrics[date] = {'type': 'product_review', 'size_kb': report_file.stat().st_size / 1024}

    for report_file in sorted(arch_dir.glob("OPP-*.md")):
        # Architecture proposals for opportunities
        created = report_file.stat().st_mtime
        created_date = datetime.fromtimestamp(created).strftime("%Y-%m-%d")
        metrics[created_date] = {'type': 'opportunity_architecture', 'size_kb': report_file.stat().st_size / 1024}

    return "Gina (Enterprise Architect)", metrics

def analyze_tech_docs():
    """Analyze John's technical documentation work"""
    docs_dir = Path("ron_skills")
    metrics = {}

    # Count INSTALL.md and README.md files in products
    doc_count = 0
    for product_dir in docs_dir.glob("*/"):
        for doc_file in product_dir.glob("*.md"):
            if doc_file.name in ["README.md", "INSTALL.md", "CHANGELOG.md"]:
                doc_count += 1
                mtime = doc_file.stat().st_mtime
                doc_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                if doc_date not in metrics:
                    metrics[doc_date] = {'docs_updated': 0}
                metrics[doc_date]['docs_updated'] += 1

    return "John (Technical Documentation)", metrics

def analyze_scout_reports():
    """Analyze Scout's opportunity research reports"""
    opp_dir = Path.home() / "Documents" / "Claude" / "Projects" / "Side Hustle" / "Opportunities"
    metrics = {}

    if opp_dir.exists():
        # Look for LATEST_SCOUT_REPORT and timestamped versions
        latest = opp_dir / "LATEST_SCOUT_REPORT.html"
        if latest.exists():
            mtime = latest.stat().st_mtime
            date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            metrics[date] = {'type': 'scout_report', 'size_kb': latest.stat().st_size / 1024}

        # Count timestamped reports
        for report_file in sorted(opp_dir.glob("SCOUT_REPORT_*.html")):
            date = parse_date_from_filename(report_file.name)
            if date:
                metrics[date] = {'type': 'scout_report', 'size_kb': report_file.stat().st_size / 1024}

    return "Scout (Product Research)", metrics

def analyze_competitive_intelligence():
    """Analyze Competitive Intelligence reports"""
    # Competitive intel may be in docs/internal/ or tracked via pipeline
    intel_dir = Path("docs/internal/competitive")
    metrics = {}

    if intel_dir.exists():
        for report_file in intel_dir.glob("*.md"):
            mtime = report_file.stat().st_mtime
            date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            metrics[date] = {'type': 'competitive_scan', 'size_kb': report_file.stat().st_size / 1024}

    return "Competitive Intelligence", metrics

def count_commits_by_agent(agent_name):
    """Count commits by specific agent"""
    result = os.popen(f"git log --all --oneline --since='2026-03-20' | grep -i '{agent_name}' | wc -l || echo '0'").read().strip()
    return int(result) if result.isdigit() else 0

def main():
    print("\n" + "="*80)
    print("COMPREHENSIVE AGENT METRICS REPORT - 2026-04-04")
    print("="*80)

    # Analyze each agent
    agents_data = []

    # Meg
    agent_name, meg_metrics = analyze_qa_reports()
    print(f"\n[{agent_name}] - QA Engineer")
    print(f"  Reports generated: {len(meg_metrics)}")
    if meg_metrics:
        total_tests = sum(m['tests'] for m in meg_metrics.values())
        print(f"  Total tests written: {total_tests}")
        print(f"  Avg tests/report: {total_tests // len(meg_metrics)}")
        print(f"  Recent status: {list(meg_metrics.values())[-1]['severity']}")
    agents_data.append((agent_name, len(meg_metrics)))

    # Brock
    agent_name, brock_metrics = analyze_security_reports()
    print(f"\n[{agent_name}] - Security Expert")
    print(f"  Reports generated: {len(brock_metrics)}")
    if brock_metrics:
        total_findings = sum(m.get('findings', 0) for m in brock_metrics.values())
        print(f"  Total findings tracked: {total_findings}")
        print(f"  Recent posture: {list(brock_metrics.values())[-1]['severity']}")
    agents_data.append((agent_name, len(brock_metrics)))

    # Jacqueline (split daily/weekly)
    agent_name, jaq_metrics = analyze_pm_reports()
    print(f"\n[{agent_name}] - Project Manager")
    print(f"  Daily dashboards: {len(jaq_metrics.get('daily', {}))}")
    print(f"  Weekly roadmaps: {len(jaq_metrics.get('weekly', {}))}")
    print(f"  Total PM artifacts: {len(jaq_metrics.get('daily', {})) + len(jaq_metrics.get('weekly', {}))}")
    agents_data.append((f"{agent_name} (daily)", len(jaq_metrics.get('daily', {}))))
    agents_data.append((f"{agent_name} (weekly)", len(jaq_metrics.get('weekly', {}))))

    # Gina
    agent_name, gina_metrics = analyze_architecture_reports()
    print(f"\n[{agent_name}] - Enterprise Architect")
    print(f"  Architecture reviews: {len(gina_metrics)}")
    if gina_metrics:
        print(f"  Latest review: {list(gina_metrics.keys())[-1] if gina_metrics else 'N/A'}")
    agents_data.append((agent_name, len(gina_metrics)))

    # Madison
    agent_name, madison_metrics = analyze_marketing_reports()
    print(f"\n[{agent_name}] - Marketing Creator")
    print(f"  Marketing artifacts: {len(madison_metrics)}")
    if madison_metrics:
        print(f"  Latest: {list(madison_metrics.keys())[-1] if madison_metrics else 'N/A'}")
    agents_data.append((agent_name, len(madison_metrics)))

    # John
    agent_name, john_metrics = analyze_tech_docs()
    print(f"\n[{agent_name}] - Technical Documentation")
    print(f"  Documentation updates tracked: {sum(m.get('docs_updated', 0) for m in john_metrics.values())}")
    agents_data.append((agent_name, len(john_metrics)))

    # Scout
    agent_name, scout_metrics = analyze_scout_reports()
    print(f"\n[{agent_name}] - Product Research")
    print(f"  Scout reports generated: {len(scout_metrics)}")
    agents_data.append((agent_name, len(scout_metrics)))

    # Competitive Intelligence
    agent_name, comp_metrics = analyze_competitive_intelligence()
    print(f"\n[{agent_name}]")
    print(f"  Competitive intelligence reports: {len(comp_metrics)}")
    agents_data.append((agent_name, len(comp_metrics)))

    # Git commit summary
    print(f"\n[GIT COMMIT ACTIVITY (last 15 days)]")
    commit_counts = {}
    for agent_keyword in ["Ron", "Meg", "Brock", "Scout", "Gina", "Madison", "John", "Jacqueline"]:
        count = count_commits_by_agent(agent_keyword)
        if count > 0:
            commit_counts[agent_keyword] = count

    for agent in sorted(commit_counts.keys(), key=lambda x: commit_counts[x], reverse=True):
        print(f"  {agent}: {commit_counts[agent]} commits")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY BY ACTIVITY LEVEL")
    print("="*80)

    agents_data.sort(key=lambda x: x[1], reverse=True)
    for agent, count in agents_data:
        if count > 0:
            print(f"  {agent}: {count} artifacts/runs")

    print("\n" + "="*80)
    print("COST OPTIMIZATION CANDIDATES (by frequency + token usage)")
    print("="*80)

    print("""
1. MEG (QA) - DAILY - HIGH COST
   - Current: Claude writes tests + analyzes code
   - Local model: Qwen pre-analyzes files → Claude writes tests (15% faster)

2. BROCK (Security) - DAILY - HIGH COST
   - Current: Claude scans all code + dependency audit
   - Local model: Qwen screens files → Claude deep-dives flagged items (20% savings)

3. JACQUELINE (PM) - DAILY - MEDIUM COST
   - Current: Claude reads all agent reports + synthesizes dashboard
   - Local model: Qwen extracts metrics/findings from reports (10-15% faster)

4. SCOUT (Research) - WEEKLY - MEDIUM COST (but high per-item)
   - Current: Claude researches 10-15 opportunities deeply
   - Local model: Gemma pre-filters for viability (30-40% cost reduction)

5. JOHN (Docs) - 2x/WEEK - LOW COST
   - Current: Claude generates documentation from code
   - Local model: Gemma scaffolds templates (10-15% faster)

6. GINA (Architecture) - 2x/WEEK - MEDIUM COST
   - Current: Claude designs architecture + feasibility
   - Local model: Could validate design against patterns (if applicable)

7. MADISON (Marketing) - 2x/WEEK - MEDIUM COST
   - Current: Claude writes blog posts + marketing copy
   - Local model: Harder to accelerate (needs creativity/brand voice)

8. COMPETITIVE INTELLIGENCE - VARIES
   - Current: Claude analyzes competitive landscape
   - Local model: Could filter obvious noise first

9. RON (Developer) - AS NEEDED - VARIABLE COST
   - Current: Claude writes product code
   - Local model: Could do code review/refactoring suggestions (post-generate)
""")

    print("="*80)

if __name__ == "__main__":
    main()
