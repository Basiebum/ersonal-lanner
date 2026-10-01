# wigbo.nl

Personal website of Bastiaan Wigboldus — a single Flask page (`templates/landing.html`)
with images in `static/images/`.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Deploy

Deployed on Render with `gunicorn app:app` (see `Procfile`). No environment variables are needed.

## Archive

The earlier version with the planner, login and training dashboard is preserved
under the git tag `archive/full-app-2026-10-01`.
