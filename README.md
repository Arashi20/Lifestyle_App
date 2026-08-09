# Skincare & Haircare Tracker

A personal, single-user app for tracking skincare products, haircut history, and
scanning product ingredients against a personal ingredient watchlist.

## Features

- **Products** — track products by status (wishlist / currently using / finished /
  abandoned), rate them, and note what worked or didn't
- **Haircuts** — log haircuts with "how to request this again" notes and an
  optional photo link
- **Ingredient scanner** — scan a barcode in-store to pull ingredients from
  [Open Beauty Facts](https://world.openbeautyfacts.org/), or fall back to OCR on
  a photo of the ingredient list
- **Ingredient watchlist** — flag ingredients as avoid / caution / good; matches
  are computed live against every product's ingredient list
- **Goodness score** — a 0-100 heuristic per product based on matched watchlist
  ingredients and ingredient list length
- **Single-user login gate** — the whole app sits behind a login with a sliding
  inactivity timeout
- Installable to a phone home screen (manifest + icons)

## Tech stack

- **Backend:** Flask + Flask-SQLAlchemy + Flask-Migrate
- **Frontend:** Server-rendered Jinja templates + htmx, no JS build step
- **Barcode scanning:** [html5-qrcode](https://github.com/mebjas/html5-qrcode) (client-side)
- **OCR fallback:** [pytesseract](https://github.com/madmaze/pytesseract) (requires the system Tesseract binary — see below)
- **Database:** PostgreSQL in production, SQLite for local dev
- **Hosting:** [Railway](https://railway.app/)

## Local setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

copy .env.example .env         # macOS/Linux: cp .env.example .env
# then edit .env — at minimum set a real SECRET_KEY

flask db upgrade                # create the local SQLite database
flask seed-watchlist             # optional: curated starter ingredient watchlist
flask set-password                # set your login username/password (prompts interactively)

python run.py
```

### OCR / Tesseract

`pytesseract` is just a wrapper — it needs the actual Tesseract OCR engine
installed separately:

- **Windows:** `winget install UB-Mannheim.TesseractOCR`, then set
  `TESSERACT_CMD` in `.env` to the installed binary path (the installer doesn't
  add itself to PATH)
- **Production (Railway):** handled automatically by `nixpacks.toml`, which
  installs the `tesseract-ocr` apt package during the build

## Deployment

Deployed on Railway with a Postgres addon. `Procfile` runs the app via
`gunicorn`; `nixpacks.toml` adds the `tesseract-ocr` system package that
Railway's default build doesn't include. Set the same environment variables
from `.env.example` (with real values) in Railway's project settings,
including a fresh `SECRET_KEY` and login credentials via `flask set-password`
run against the production database.
