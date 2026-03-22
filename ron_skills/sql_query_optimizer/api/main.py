"""
SQL Query Optimizer API - Premium Backend
==========================================
This is the paid service behind the free ClawHub skill.
Free skill does pattern detection locally; this API does the heavy lifting:
  - Full query rewrites with explanations
  - Index recommendations with CREATE INDEX statements
  - Execution plan analysis
  - Dialect-specific optimization (T-SQL, MySQL, PostgreSQL, SQLite)

Revenue model: credit-based. Each optimization call costs 1 credit.
Users buy credit packs via Stripe ($9.99/50 credits, $29.99/200 credits, $79.99/unlimited monthly).
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # Load .env file before anything reads environment variables

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from optimizer import SQLOptimizer
from credits import CreditManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_VERSION = "1.0.0"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("sql_optimizer_api")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SQL Query Optimizer API",
    version=API_VERSION,
    description="Premium SQL optimization powered by AI. Free analysis on ClawHub, full rewrites here.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class QueryContext(BaseModel):
    table_info: Optional[str] = Field(None, description="Schema info (CREATE TABLE statements, column types, etc.)")
    database_engine: Optional[str] = Field(None, description="Engine version (e.g., 'SQL Server 2019', 'PostgreSQL 16')")

class OptimizeRequest(BaseModel):
    query: str = Field(..., description="The SQL query to optimize", min_length=5)
    dialect: str = Field("tsql", description="SQL dialect: tsql, mysql, postgresql, sqlite")
    context: Optional[QueryContext] = None

class OptimizeResponse(BaseModel):
    original_query: str
    optimized_query: str
    dialect: str
    changes: list[dict]
    index_recommendations: list[dict]
    execution_analysis: dict
    credits_remaining: int
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str

class CreditsResponse(BaseModel):
    api_key: str
    credits_remaining: int
    plan: str

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
credit_manager = CreditManager()
optimizer = SQLOptimizer()

async def verify_api_key(authorization: str = Header(...)) -> str:
    """Extract and validate the API key from the Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header. Use: Bearer <api_key>")

    api_key = authorization.replace("Bearer ", "").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="API key is required")

    if not credit_manager.is_valid_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key. Get one at https://sqloptimizer.ronagent.com")

    return api_key

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint -- no auth required."""
    return HealthResponse(
        status="healthy",
        version=API_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/v1/optimize", response_model=OptimizeResponse)
async def optimize_query(request: OptimizeRequest, api_key: str = Depends(verify_api_key)):
    """
    Optimize a SQL query. Costs 1 credit per call.

    Returns the optimized query, a list of changes with explanations,
    index recommendations, and execution analysis.
    """
    # Check credits
    remaining = credit_manager.get_credits(api_key)
    if remaining <= 0:
        raise HTTPException(
            status_code=402,
            detail="No credits remaining. Purchase more at https://sqloptimizer.ronagent.com/pricing",
        )

    # Validate dialect
    valid_dialects = {"tsql", "mysql", "postgresql", "sqlite"}
    dialect = request.dialect.lower()
    if dialect not in valid_dialects:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dialect '{request.dialect}'. Must be one of: {', '.join(sorted(valid_dialects))}",
        )

    # Run optimization
    logger.info("Optimizing query for key=%s..., dialect=%s", api_key[:8], dialect)
    try:
        result = await optimizer.optimize(
            query=request.query,
            dialect=dialect,
            table_info=request.context.table_info if request.context else None,
            database_engine=request.context.database_engine if request.context else None,
        )
    except Exception as e:
        logger.error("Optimization failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Optimization failed. Please try again.")

    # Deduct credit
    credit_manager.use_credit(api_key)
    credits_remaining = credit_manager.get_credits(api_key)

    return OptimizeResponse(
        original_query=request.query,
        optimized_query=result["optimized_query"],
        dialect=dialect,
        changes=result["changes"],
        index_recommendations=result["index_recommendations"],
        execution_analysis=result["execution_analysis"],
        credits_remaining=credits_remaining,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/v1/credits", response_model=CreditsResponse)
async def check_credits(api_key: str = Depends(verify_api_key)):
    """Check remaining credits for an API key."""
    return CreditsResponse(
        api_key=f"{api_key[:8]}...",
        credits_remaining=credit_manager.get_credits(api_key),
        plan=credit_manager.get_plan(api_key),
    )
