# AI Job Hunter ATS — Phase 1

A functional personal job discovery, ranking and application tracking app. Built for two tracks: (A) sales/executive education and (B) growth/product operations. It does **not** automatically apply to jobs or scrape LinkedIn.

## Run locally on macOS

Recommended: Python **3.11 or 3.12**. macOS system Python 3.9.6 is old; newer dependencies may not support it.

1. Unzip this folder into Downloads.
2. In Terminal:

```bash
cd ~/Downloads/ai_job_hunter_ats
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

If you have Python 3.12 installed, replace `python3 -m venv` with `python3.12 -m venv`.

Local storage uses SQLite in `job_hunter.db`. Back up that file or export your CSV regularly.

## Host online (Streamlit Community Cloud + Supabase)

1. Create a **private GitHub repository**, add `app.py`, `requirements.txt`, and `supabase.sql` (do not commit real secrets, database files or your resume).
2. Create a Supabase project. Open SQL Editor and run `supabase.sql`.
3. In Supabase project settings, locate the project URL and **service role key**. The service role key is highly privileged: never publish it, put it in frontend code, or commit it to Git.
4. Deploy the repo in Streamlit Community Cloud using `app.py` as entrypoint.
5. In Streamlit app settings → Secrets, enter:

```toml
APP_PASSWORD = "a-long-unique-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

6. Restart the app. Sidebar should show `Supabase connected`. Access is gated by your app password; use a strong unique one. This is a **single-user prototype**, not enterprise authentication. Avoid storing sensitive personal data beyond what you need.

**Important:** Without Supabase, a cloud deployment's SQLite data may be lost on redeploy/restart. The app explicitly warns about this.

## Job discovery

- Remotive and Arbeitnow public APIs: available through the Discover page; may be skewed toward international tech roles.
- Greenhouse: enter a company **board token** (the segment after `boards.greenhouse.io/`).
- Lever: enter a company **site token** (the segment after `jobs.lever.co/`).
- Only public postings from these sources are fetched. No guarantee of comprehensive India job coverage, up-to-date salaries, or API uptime.
- Ranking is a transparent heuristic. It is **not** an employer ATS score, AI model, or probability of being hired. Salary is not inferred from unstructured text.

## Emeritus application

In **Add application**, click **Prefill Emeritus Program Advisor**, verify all fields, and click Save. We do not automatically mark it saved because no database was connected to your account during creation.

## Future phases

Phase 2: explainable LLM-assisted JD analysis, skill evidence from your verified resume, and tailored resume suggestions (with an opt-in API key).
Phase 3: more India-relevant employer feeds, scheduled ingestion, notifications and analytics.
