# Helpdesk Hub

A full-stack, role-based help desk starter built with Flask and SQLAlchemy. It runs locally with SQLite and can be deployed as a free Render web service backed by a persistent external PostgreSQL database.

## Included workflows
- Customer sign-up/sign-in; role-based customer, agent, team lead, and admin views.
- Unique `HD-YYYY-NNNN` tickets; category, five urgency levels, status transitions, agent assignment/reassignment, and escalation.
- Public replies and staff-only internal notes, activity timeline, notification inbox, customer feedback.
- Priority-based first-response/resolution targets, breach/at-risk indicators, and operational dashboard.
- Agent workload, searchable/filterable queues, knowledge base, CSV reports, user/agent administration, profile editing.
- CSRF-protected forms, password hashing, server-side permissions and input validation.

## Run locally
Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000. Local SQLite creates `helpdesk.db` automatically and seeds a demo workspace on first run.

Demo credentials:

| Role | Email | Password |
|---|---|---|
| Customer | customer@helpdesk.com.kh | Customer123! |
| Agent | agent@helpdesk.com.kh | Agent123! |
| Team lead | lead@helpdesk.com.kh | Lead123! |
| Admin | admin@helpdesk.com.kh | Admin123! |

## Free cloud deployment (Render + Supabase)
Render's free web service can host the application, but its filesystem is ephemeral and its free Postgres currently expires after 30 days. For a demo that needs data to persist beyond that, use a free external PostgreSQL provider such as Supabase for the database, and Render for the web app. Free-tier offers/limits can change; verify them before relying on the service for important data.

1. Create a GitHub repository and push this folder. Do not commit secrets or a real production database file.
2. Create a Supabase project on its free plan. In the Supabase dashboard, open **Connect** and copy the **Session pooler** PostgreSQL connection string. Use Session mode (port 5432), not Direct—Render's free services are IPv4-only and Supabase's direct endpoint may be IPv6-only. Replace the password placeholder; keep the pooler username exactly as provided. It should begin `postgresql://...` or `postgres://...`.
3. In Render, choose **New → Blueprint**, connect your repository, and apply `render.yaml`.
4. Set `DATABASE_URL` to the Supabase connection string. Render generates `SECRET_KEY`. Keep `SEED_DEMO=false`. Set `ADMIN_EMAIL` and a strong unique `ADMIN_PASSWORD` (12+ characters); the app creates this initial administrator once if no admin exists. You can remove those two environment values after first boot.
5. Deploy. The service runs `gunicorn app:app`; `/health` is the health check.
6. Sign in with the initial admin email/password, create support agents and team leads under **Team & access**, then have customers register or add customer accounts. Do not set `SEED_DEMO=true` on a public deployment; it creates public demo credentials.

### Important free-tier caveats
- Render's free web services sleep when idle and take time to wake; uploaded files are stored on the app's local filesystem and are not durable across restarts or deploys. Use an object-storage service (for example, Supabase Storage) before relying on cloud attachments. Database data remains in the external Postgres service.
- Free external databases may pause on inactivity, have storage caps, or change terms. Export backups regularly.
- This is an educational/MVP foundation, not a hardened production service. Before real-world use add durable private attachment storage, email/SMS delivery, password reset and MFA, rate limiting, stronger audit retention, configured business-hours calendars, and an admin bootstrap workflow. SLA clocks currently use elapsed UTC hours, not business hours or holidays.

## Priority SLA defaults

| Priority | First response | Resolution |
|---|---:|---:|
| Low | 24 h | 120 h |
| Medium | 8 h | 72 h |
| High | 4 h | 24 h |
| Urgent | 1 h | 8 h |
| Critical | 30 min | 4 h |

Edit `SLA_HOURS` in `app.py` to tune these targets. Export reports from **Reports & analytics → Export CSV**.

## Testing smoke check
Start the app and visit `/health` (expected `{"status":"ok"}`), sign in as each demo role, create a ticket as customer, assign/reply/update status as lead or agent, and confirm report export as lead/admin.
