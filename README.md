Summary

This project is a planner web app. To sync between devices we use Supabase as the Postgres/json store. There are two ways to run this project:

1) Preferred (client-only): Serve the `templates/index.html` as a static site and use `supabase-js` in the browser to read/write the `plans` table.

2) Server-backed (this repo): Run the Flask app which talks to Supabase using a secure `service_role` key. The Flask app exposes two endpoints:
   - `POST /api/save` -> insert a plan JSON into `plans`
   - `GET /api/plans` -> list plans (optionally filter by `user_id`)

Setup (server-backed)

- Create a Supabase project and a table `plans` with this example SQL (run in SQL editor):

```
create extension if not exists pgcrypto;

create table public.plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  name text,
  data jsonb,
  created_at timestamptz default now()
);
```

- Set environment variables on your host:
  - `SUPABASE_URL` = https://<project-ref>.supabase.co
  - `SUPABASE_SERVICE_KEY` = <service_role_key> (keep this secret)

- Install dependencies and run locally:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Notes

- Supabase does not host Python servers — if you want the app to be hosted on Supabase Hosting, use the client-only approach (supabase-js) and deploy the built static files there.
- Never embed `service_role` keys into client-side code. Use anon/public keys (`anon` key) in browser apps.

Deploying the Flask app (recommended: Render / Railway / Heroku)

1) Prepare the repo

- Ensure `requirements.txt` includes `gunicorn` (already present).
- Add a `Procfile` with: `web: gunicorn app:app` (already present).

2) Create a Supabase table

Run the SQL above in the Supabase SQL editor to create `plans`.

3) Deploy to Render (example)

- Sign in to https://dashboard.render.com and create a new Web Service.
- Connect your GitHub repo (or do a manual deploy).
- Set the start command to `gunicorn app:app` if Render doesn't detect it automatically.
- Add environment variables in the Render dashboard:
  - `SUPABASE_URL` = https://<project-ref>.supabase.co
  - `SUPABASE_SERVICE_KEY` = <service_role_key> (KEEP SECRET)
- Deploy. Render will provide a public HTTPS URL you can open from any device.

4) Access from phone/laptop

- Open the Render-provided HTTPS URL on any device. Because the Flask server uses Supabase for storage, data will sync between devices when you use the app's Sync button.

Notes about keys and security

- Do not expose your `service_role` key to clients. The server uses it to write/read data securely.
- For per-user isolation, implement Supabase Auth and pass `user_id` from the client to the server API so saved plans are scoped to each user.
