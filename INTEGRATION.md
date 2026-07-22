# Integrating the training dashboard into your existing site

This turns the training dashboard into a **Flask Blueprint** mounted at
`/training` on your existing app, so it becomes `wigbo.nl/training`.

## What's in this folder

```
app.py                 # your existing app.py, with minimal edits (see diff below)
supabase_client.py      # NEW — shared Supabase client, used by app.py and training/
supabase_schema.sql     # NEW — run once in Supabase SQL editor to create tables
training/                # NEW — the whole training dashboard, as a blueprint
  __init__.py
  routes.py
  strava.py
  ai_edit.py
  templates/training/    # namespaced so it won't clash with your templates/
  static/css/             # served at /training/static/css/...
```

## 1. Copy files into your project

Copy `supabase_client.py`, `supabase_schema.sql`, and the whole `training/`
folder into your `coding/supabase/` project root, next to your existing
`app.py`.

Then apply the same change to your real `app.py` that's in this folder —
it's your original file with only this diff:

**Removed:**
```python
from supabase import create_client
...
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
```

**Added:**
```python
from supabase_client import supabase, SUPABASE_URL, SUPABASE_KEY

from training import training_bp
app.register_blueprint(training_bp, url_prefix="/training")
```

Everything else in your `app.py` — login, register, `/api/save`, `/health`,
etc. — is untouched.

## 2. Create the Supabase tables

Open your Supabase project → SQL Editor → paste in `supabase_schema.sql` →
Run. **Before running it**, check your `users.id` column type in Table
Editor — the script assumes `uuid`; if yours is `bigint`, swap the type as
noted in the comments at the top of the file.

## 3. Add environment variables

Alongside your existing `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`, add on
Render (Dashboard → your service → Environment):

```
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=https://wigbo.nl/training/strava/callback
ANTHROPIC_API_KEY=...          # optional, enables the AI plan editor
```

Get Strava credentials at https://www.strava.com/settings/api — set
"Authorization Callback Domain" to `wigbo.nl`.

## 4. Update requirements.txt

Add these lines to your existing `requirements.txt` if not already present:

```
requests
anthropic
```

(`flask`, `supabase`, `werkzeug`, `gunicorn` you already have.)

## 5. How login works here

`/training` reuses your existing session-based login — it checks
`session['user_id']`, same as `/planner` does. If someone isn't logged in,
visiting `/training` redirects to `/login`, same as the rest of your site.
No separate auth system.

## 6. Deploy

Commit, push, redeploy on Render as usual. Then visit `wigbo.nl/training`
while logged in.

## 7. Optional: link it from your site

Add a link to `/training` somewhere in your `index.html` / `landing.html`
nav so it's reachable without typing the URL directly.
