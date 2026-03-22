"""
SQL Optimizer Engine
====================
Uses Claude API to analyze and rewrite SQL queries.
This is the core intelligence behind the paid tier.

The optimizer:
1. Sends the query + dialect + schema context to Claude
2. Gets back a structured optimization with explanations
3. Returns it in a consistent format for the API

Cost per optimization: ~500-2000 tokens input, ~1000-3000 tokens output
At Sonnet 4.5 pricing ($3/$15 per 1M tokens): ~$0.005-$0.05 per call
Selling at 1 credit = ~$0.20-$0.40, so ~4-80x margin.
"""

import os
import json
import logging
from typing import Optional

import anthropic

logger = logging.getLogger("sql_optimizer_api.optimizer")

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert SQL performance tuner with 20 years of experience across
SQL Server (T-SQL), MySQL, PostgreSQL, and SQLite.

When given a SQL query, you:
1. Identify ALL performance issues
2. Rewrite the query for optimal performance
3. Recommend specific indexes (with CREATE INDEX statements)
4. Analyze the likely execution plan bottlenecks

You MUST respond with valid JSON matching this exact structure:
{
  "optimized_query": "the rewritten SQL query",
  "changes": [
    {
      "description": "what was changed",
      "reason": "why this improves performance",
      "impact": "high|medium|low"
    }
  ],
  "index_recommendations": [
    {
      "statement": "CREATE INDEX ...",
      "reason": "why this index helps",
      "estimated_impact": "description of expected improvement"
    }
  ],
  "execution_analysis": {
    "bottlenecks": ["list of identified bottlenecks"],
    "estimated_improvement": "rough estimate like '2-5x faster' or '60-80% reduction in reads'",
    "notes": "any caveats or things the user should verify"
  }
}

Rules:
- ONLY output valid JSON, no markdown fences, no explanation outside the JSON
- Be specific -- generic advice is worthless
- If the query is already well-optimized, say so honestly in the changes array
- Tailor advice to the specific dialect (T-SQL vs MySQL vs PostgreSQL vs SQLite)
- Include CREATE INDEX statements with the correct syntax for the dialect
- Never invent table/column names not present in the query or schema context"""


def _build_user_prompt(
    query: str,
    dialect: str,
    table_info: Optional[str] = None,
    database_engine: Optional[str] = None,
) -> str:
    """Build the user prompt with all available context."""
    parts = [f"Dialect: {dialect}"]

    if database_engine:
        parts.append(f"Engine: {database_engine}")

    if table_info:
        parts.append(f"Schema context:\n{table_info}")

    parts.append(f"Query to optimize:\n{query}")

    return "\n\n".join(parts)


class SQLOptimizer:
    """Wraps the Claude API to provide SQL optimization."""

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set. Optimizer will fail on real requests. "
                "Set it in your environment or .env file."
            )
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self.model = os.getenv("OPTIMIZER_MODEL", "claude-sonnet-4-5-20250514")

    async def optimize(
        self,
        query: str,
        dialect: str = "tsql",
        table_info: Optional[str] = None,
        database_engine: Optional[str] = None,
    ) -> dict:
        """
        Optimize a SQL query using Claude.

        Returns a dict with keys:
          - optimized_query: str
          - changes: list[dict]
          - index_recommendations: list[dict]
          - execution_analysis: dict
        """
        if not self.client:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        user_prompt = _build_user_prompt(query, dialect, table_info, database_engine)

        logger.info("Calling Claude (%s) for %s optimization...", self.model, dialect)

        # Using sync client in async context -- for production, switch to
        # anthropic.AsyncAnthropic. Fine for MVP throughput.
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Extract text content
        raw_text = message.content[0].text.strip()

        # Parse JSON response
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            # Sometimes Claude wraps in markdown fences despite instructions
            cleaned = raw_text
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            try:
                result = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error("Failed to parse Claude response as JSON: %s", raw_text[:200])
                raise ValueError("Optimizer returned invalid response. Please try again.")

        # Validate expected keys
        required_keys = {"optimized_query", "changes", "index_recommendations", "execution_analysis"}
        missing = required_keys - set(result.keys())
        if missing:
            logger.error("Missing keys in optimizer response: %s", missing)
            raise ValueError(f"Optimizer response missing required fields: {missing}")

        logger.info(
            "Optimization complete: %d changes, %d index recommendations",
            len(result["changes"]),
            len(result["index_recommendations"]),
        )

        return result
