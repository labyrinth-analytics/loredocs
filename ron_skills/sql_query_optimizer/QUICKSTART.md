# SQL Query Optimizer - Quickstart

## What's In This Folder

```
sql_query_optimizer/
  QUICKSTART.md          <-- you are here
  skill/
    SKILL.md             <-- FREE ClawHub skill (submit to github.com/openclaw/clawhub)
  api/
    main.py              <-- FastAPI server (the paid backend)
    optimizer.py          <-- Claude-powered SQL optimizer engine
    credits.py            <-- API key + credit management
    requirements.txt      <-- Python dependencies
    .env.example          <-- Environment variable template
    Dockerfile            <-- Container build for deployment
    railway.toml          <-- Railway.app deployment config
    tests/
      test_credits.py     <-- Credit system tests (13/13 passing)
```

## How the Money Flows

```
User finds skill on ClawHub (FREE)
         |
         v
Skill analyzes SQL locally (FREE pattern detection)
         |
         v
User wants full rewrite + index recommendations
         |
         v
Skill calls YOUR API (costs 1 credit per optimization)
         |
         v
API calls Claude Sonnet ($0.005-$0.05 cost to you)
         |
         v
User pays you $0.15-$0.20 per credit (3-40x margin)
```

## Pricing Tiers

| Plan      | Price     | Credits | Per Optimization | Your Margin |
|-----------|-----------|---------|-----------------|-------------|
| Starter   | $9.99     | 50      | $0.20           | ~$0.15-0.19 |
| Pro       | $29.99    | 200     | $0.15           | ~$0.10-0.14 |
| Unlimited | $79.99/mo | Unlimited | ~$0.00*       | Depends on usage |

*Unlimited is profitable if users average < 1,600 optimizations/month (they will).

## To Deploy (Debbie's Steps)

### Step 1: Get Your API Keys (~10 min)
1. Get an Anthropic API key at https://console.anthropic.com
2. Create a Stripe account at https://stripe.com (for payments later)
3. Copy `.env.example` to `.env` and fill in your Anthropic key

### Step 2: Test Locally (~5 min)
```bash
cd api/
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
uvicorn main:app --reload
# Visit http://localhost:8000/docs to see the API
```

### Step 3: Deploy to Railway (~10 min)
1. Create account at https://railway.app
2. Connect your GitHub repo
3. Add environment variables (ANTHROPIC_API_KEY)
4. Deploy -- Railway auto-detects the Dockerfile
5. You get a URL like: https://sql-optimizer-production.up.railway.app

### Step 4: Update the Skill Domain
Edit `skill/SKILL.md` and replace `api.sqloptimizer.ronagent.com` with your Railway URL.

### Step 5: Submit to ClawHub (~5 min)
1. Fork https://github.com/openclaw/clawhub
2. Add the `skill/` folder
3. Open a pull request
4. Wait for merge (usually 1-3 days)

## What Ron Does Next (Autonomous)

Once deployed, Ron can:
- Monitor API usage and revenue via Railway dashboard
- Generate API keys for new customers
- Scale the service (Railway auto-scales)
- You review the weekly summary and approve any changes

## Next Skills to Build

After this one is live:
- [ ] Financial Report Generator (Skill #2)
- [ ] CSV/Excel Data Transformer (Skill #3)

Same architecture: free skill + paid API backend.
