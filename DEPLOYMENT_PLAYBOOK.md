# Veranda — Deployment Playbook

This document covers everything needed to take Veranda from a local Streamlit
app to a live, secure, web-accessible product. Do not deploy until data
enrichment is complete.

---

## Current Stack (Local)

| Layer        | Technology                        |
|--------------|-----------------------------------|
| Frontend     | Streamlit (runs on localhost:8501)|
| Database     | SQLite (data/veranda.db)          |
| AI / Outreach| Groq API (GROQ_API_KEY in .env)   |
| Data sync    | scripts/sync_leads.py (run manually on Mac) |
| Auth         | None (local only)                 |
| Secrets      | .env file on laptop               |

---

## Target Stack (Production)

| Layer        | Technology                        |
|--------------|-----------------------------------|
| Frontend     | Streamlit on Railway              |
| Database     | PostgreSQL on Supabase            |
| AI / Outreach| Groq API (secret in Railway)      |
| Data sync    | GitHub Actions cron job           |
| Auth         | Cloudflare Access                 |
| Secrets      | Railway + GitHub Actions env vars |
| Domain / SSL | Cloudflare (custom domain)        |

---

## Architecture Diagram

```
User (browser)
    │
    ▼
Cloudflare (auth + SSL + custom domain)
    │
    ▼
Railway (Streamlit app — always-on server)
    │                   │
    ▼                   ▼
Supabase            Groq API
(PostgreSQL)        (AI outreach generation)
    ▲
    │
GitHub Actions
(sync cron — runs every 12 weeks)
    │
    ▼
NYC Socrata API / SEC EDGAR / FEC
```

---

## Step 1 — Migrate Database: SQLite → PostgreSQL

### Why
SQLite is a single file on the local machine. Cloud hosting platforms use
ephemeral filesystems — the file is wiped on every restart. PostgreSQL is a
real server that lives independently of the app and supports multiple
concurrent users.

### Where
Sign up for Supabase (https://supabase.com) — free tier includes a managed
PostgreSQL instance with enough capacity for Veranda's data volume.

### Code Changes
- Update src/db.py to use psycopg2 (or SQLAlchemy) instead of sqlite3.
  The SQL queries are almost identical since we already use standard SQL.
- Add psycopg2-binary to requirements.txt.
- Replace the DATABASE_URL default path logic with an environment variable:
    DATABASE_URL=postgresql://user:password@host:5432/veranda
- The connection string comes from Supabase's dashboard under
  Settings → Database → Connection string.

### Data Migration (one-time)
Run a migration script to export all rows from SQLite and INSERT them into
the new PostgreSQL database. This preserves all existing leads, outreach
drafts, and sync logs.

### Estimated Effort: 2–3 hours

---

## Step 2 — Deploy Frontend to Railway

### Why Railway
- Always-on server (unlike Streamlit Community Cloud which sleeps after
  inactivity and loses state).
- Native PostgreSQL add-on (or connect to Supabase directly).
- GitHub integration: push to main → auto-deploys in ~2 minutes.
- Cheap: ~$5/month for a hobby plan.

### Steps
1. Create an account at https://railway.app.
2. Create a new project → "Deploy from GitHub repo" → select beradem/veranda.
3. Railway detects Python automatically. Set the start command to:
       streamlit run app.py --server.port $PORT --server.address 0.0.0.0
4. Add all environment variables in Railway's dashboard (see Secrets section).
5. Railway provides a free .railway.app subdomain immediately.
6. Later, connect a custom domain (e.g. app.veranda.co) via the Settings tab.

### Estimated Effort: 1 hour

---

## Step 3 — Secrets & Environment Variables

Never commit secrets to GitHub. Each platform has its own secrets dashboard.

| Variable            | Value source                             | Used by                    |
|---------------------|------------------------------------------|----------------------------|
| DATABASE_URL        | Supabase dashboard                       | src/db.py                  |
| GROQ_API_KEY        | console.groq.com → API Keys              | outreach_generator         |
| SOCRATA_APP_TOKEN   | data.cityofnewyork.us → My Profile       | real_estate engine         |
| PDL_API_KEY         | console.peopledatalabs.com → API Keys    | contact_reveal engine      |

In Railway: Settings → Variables → add each key/value pair.
In GitHub Actions: repo Settings → Secrets and variables → Actions → New secret.

No code changes needed for Groq or Socrata — they already read from
environment variables. Only DATABASE_URL requires updating db.py.

---

## Step 4 — Automate Data Sync with GitHub Actions

### Why
scripts/sync_leads.py currently runs manually on the laptop. In production
it needs to run on a schedule automatically to keep leads fresh.

### How
Create .github/workflows/sync.yml in the repo. GitHub runs this for free
on their infrastructure.

```yaml
name: Quarterly Lead Sync

on:
  schedule:
    - cron: '0 3 * */3 0'   # 3am UTC every 12 weeks (Sunday)
  workflow_dispatch:          # also allows manual trigger from GitHub UI

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: python scripts/sync_leads.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SOCRATA_APP_TOKEN: ${{ secrets.SOCRATA_APP_TOKEN }}
```

The sync job connects directly to the production PostgreSQL database
(via DATABASE_URL) and populates it with fresh leads. The app then serves
results from that live database with no changes required.

### Estimated Effort: 30 minutes

---

## Step 5 — Authentication with Cloudflare Access

### Why
Once the app is on a public URL, anyone with the link can access all leads
and use the AI outreach feature. Cloudflare Access puts a login wall in
front of the entire app with zero code changes.

### How
1. Sign up for Cloudflare (free) and add your custom domain.
2. In Zero Trust → Access → Applications → Add an application.
3. Set the app URL to your Railway domain.
4. Configure an identity provider (Google OAuth is the easiest — users log
   in with their Google account).
5. Add an Access Policy: allow only specific email addresses or a domain
   (e.g. @veranda.co) to pass through.

All traffic to the app now requires a Google login first. No Streamlit code
changes. Free for up to 50 users.

### Estimated Effort: 45 minutes

---

## Step 6 — Custom Domain

1. Buy a domain (e.g. veranda.co) via Cloudflare Registrar or Namecheap.
2. In Cloudflare DNS, add a CNAME record pointing your subdomain
   (e.g. app.veranda.co) to the Railway-provided domain.
3. Enable Cloudflare proxy (orange cloud) for SSL and DDoS protection.
4. In Railway → Settings → Domains → add your custom domain.

SSL certificate is provisioned automatically by Cloudflare. Free.

### Estimated Effort: 30 minutes

---

## Estimated Monthly Cost at Launch

| Service              | Plan          | Cost/month |
|----------------------|---------------|------------|
| Railway (app server) | Hobby         | ~$5        |
| Supabase (database)  | Free tier     | $0         |
| Cloudflare (auth/SSL)| Free tier     | $0         |
| Groq (AI)            | Pay-as-you-go | ~$5–20     |
| GitHub Actions (sync)| Free tier     | $0         |
| **Total**            |               | **~$10–25**|

---

## Pre-Launch: Contact Reveal Pricing & Credits

Before making Veranda public, implement a credits system so you can monetise
each reveal and cover the PDL API cost:

- Decide the per-reveal price to charge users (PDL costs ~$0.04–$0.10/match)
- Add a `credits` balance column to user accounts
- Deduct 1 credit on each Reveal button click; block if balance is zero
- Show "Uses 1 credit ($0.XX)" micro-copy next to each Reveal button in the UI
- Add a credit purchase flow (Stripe recommended)

---

## Recommended Order of Work

1. Enrich data (LinkedIn, phone, email lookups) — do this before deploying
   so the database is already high-quality when users land.
2. Migrate database from SQLite to PostgreSQL (Supabase).
3. Update src/db.py to use the new connection.
4. Deploy to Railway, wire in all secrets.
5. Create GitHub Actions sync workflow.
6. Set up Cloudflare Access authentication.
7. Point custom domain.

---

## Files to Change When Ready

| File                          | Change needed                                |
|-------------------------------|----------------------------------------------|
| src/db.py                     | Replace sqlite3 with psycopg2 + DATABASE_URL |
| requirements.txt              | Add psycopg2-binary                          |
| scripts/sync_leads.py         | Already works; just needs DATABASE_URL env var|
| .github/workflows/sync.yml    | Create this file (see Step 4)                |
| .streamlit/config.toml        | No changes needed                            |
| app.py                        | No changes needed                            |
