# Lifestyle Connector (MCP)

A **standalone, read-only** service that exposes the Skincare & Haircare
Tracker (**profile & sleep schedule**, **products with their ingredient
scores**, **haircuts** and the **ingredient watchlist**) to Claude as a custom
connector, and to scripts as a plain REST API.

It deploys as its own Railway service pointing at this folder, next to the main
app. It reads the same Postgres database and signs you in with the same login
variables.

```
Postgres ──┬── Lifestyle_App        (the app, read + write)
           └── Lifestyle Connector  (this folder, read only)
                     ▲
                     │ MCP over HTTPS + OAuth
                  Claude
```

## Why it is read-only

This is enforced in four separate places:

* **The database refuses writes.** Every connection this service opens is set
  to read-only (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` on
  Postgres, `PRAGMA query_only` on local SQLite). An `INSERT`/`UPDATE`/`DELETE`
  fails with *"cannot execute … in a read-only transaction"*, even if a bug
  here tried one. `/healthz` reports this as `read_only_connection: true`.
* No route accepts a write method. The REST endpoints are GET only, and the
  only POSTs are the MCP JSON-RPC and OAuth endpoints.
* Every collector in `data.py` issues SELECTs and nothing else, and every tool
  is declared with `readOnlyHint`. `check_ingredients` only computes a score
  and saves nothing.
* `models.py` here is a mirror with **no `create_all()`** and none of the main
  app's write helpers. The schema belongs to the main app's migrations.

The OAuth side stores nothing either: codes, tokens and clients are signed
values rather than database rows.

## Deploying on Railway

1. In the same Railway project: **New → GitHub Repo →** this repository.
2. **Settings → Root Directory:** `mcp`. This is what makes it its own service
   rather than a second copy of the app.
3. **Settings → Networking:** generate a domain.
4. **Variables** (replace `Lifestyle_App` with your main service's name in Railway):

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference to the same database) |
| `AUTH_USERNAME` | `${{Lifestyle_App.AUTH_USERNAME}}`: the main app's login username |
| `AUTH_PASSWORD_HASH` | `${{Lifestyle_App.AUTH_PASSWORD_HASH}}`: the main app's password hash |
| `MCP_SECRET_KEY` | Any long random string. Signs the tokens this connector issues; rotating it revokes them all. Does not have to match the main app. |
| `MCP_PUBLIC_URL` | Optional on Railway, because it defaults to the domain Railway injects. Set it only for a custom domain. |
| `MCP_ALLOWED_HOSTS` | Optional on Railway, with the same default. The Railway domain is always accepted regardless. |

Use references rather than pasted values for the login. Then running
`flask set-password` and updating the main service's variables also updates
this one. **Changing the username or password revokes every token the connector
has issued**, because each token carries a fingerprint of the login it was
issued under. After a password change, reconnect in Claude.

Optional:

| Variable | Default | What it does |
|---|---|---|
| `API_READ_TOKEN` | - | Static bearer token(s) for curl and Claude Code. Comma-separate to rotate. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `MCP_OAUTH_CLIENT_ID` / `MCP_OAUTH_CLIENT_SECRET` | - | A pre-shared OAuth client, if you would rather paste credentials into Claude than let it register itself |
| `MCP_OAUTH_REDIRECT_URIS` | Claude's callbacks | Comma-separated callbacks allowed for that pre-shared client |
| `MCP_ENABLED` | `1` | `0` turns the `/mcp` endpoint off |
| `MCP_OAUTH_ENABLED` | `1` | `0` turns the OAuth endpoints off |
| `MCP_OAUTH_ALLOW_DYNAMIC_REGISTRATION` | `1` | `0` requires the pre-shared client |

## Connecting Claude

1. Claude → **Settings → Connectors → Add custom connector**.
2. URL: `https://your-connector.up.railway.app/mcp`
3. Leave the OAuth client ID/secret blank so Claude registers itself. (Fill them
   in only if you set `MCP_OAUTH_CLIENT_ID` / `MCP_OAUTH_CLIENT_SECRET` first.)
4. **Connect**. A sign-in page appears: enter your app username and password,
   then **Approve**. Claude now holds a read-only token.

For Claude Code, the static token is simpler:

```bash
claude mcp add --transport http lifestyle https://your-connector.up.railway.app/mcp \
  --header "Authorization: Bearer $API_READ_TOKEN"
```

## Tools

| Tool | Returns |
|---|---|
| `get_overview` | The home page: skin type, preferred brands/ingredients, notes, sleep schedule and duration, product counts per status, products currently in use, favorite haircuts (≥ 8/10), latest haircut and days since, watchlist size |
| `get_products` | Products filtered by status / category / name or brand / id, each with rating, skin notes, dates and the app's ingredient analysis: goodness score and tier, warning level, and matched avoid/caution/good ingredients with reasons. The raw ingredient list is included only with `include_ingredients: true` |
| `get_haircuts` | Haircut history with ratings, descriptions and "how to request this again" notes, filterable by minimum rating or text, plus days since the last cut and the average gap between cuts |
| `get_ingredient_watchlist` | The avoid / caution / good ingredient list with reasons |
| `check_ingredients` | Scores an ingredient list you paste (e.g. a product in a shop) against the watchlist exactly as the app scores saved products. Nothing is saved |

The daily supplements shown on the home page are hard-coded in the template
rather than stored in the database, so the connector does not expose them.

## REST

```bash
curl -H "Authorization: Bearer $API_READ_TOKEN" https://your-connector.up.railway.app/api/v1/ping
curl -H "Authorization: Bearer $API_READ_TOKEN" https://your-connector.up.railway.app/api/v1/overview
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/products?status=currently_using"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/products?id=3&include_ingredients=true"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/haircuts?min_rating=8"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/watchlist?severity=avoid"
curl -H "Authorization: Bearer $API_READ_TOKEN" --get "https://your-connector.up.railway.app/api/v1/check-ingredients" \
  --data-urlencode "ingredients=Aqua, Glycerin, Coconut Oil, Niacinamide"
```

Unauthenticated helpers: `GET /` describes the service, and `GET /healthz`
reports the database connection, whether it is read-only, whether the login
variables are set, and the settings that decide whether the OAuth handshake can
work. Open it first when Claude cannot connect:

```json
{
  "status": "ok",
  "database": "reachable",
  "read_only_connection": true,
  "login_configured": true,
  "public_base_url": "https://your-connector.up.railway.app",
  "request_host": "your-connector.up.railway.app",
  "public_url_matches_request": true,
  "allowed_hosts": ["your-connector.up.railway.app"],
  "oauth_enabled": true,
  "dynamic_registration": true
}
```

`public_url_matches_request: false` is the usual cause of "Couldn't register
with the sign-in service". Every OAuth endpoint Claude is told to call is built
from `public_base_url`, so if it names a host that isn't this service, the
registration request never arrives. `login_configured: false` means the
`AUTH_*` references are missing, so the sign-in page can't accept anyone. In
both cases the response has a `warning` field that says what to change.

## Files

| File | What it holds |
|---|---|
| `server.py` | App factory, read-only DB connections, Host allow-list, `/`, `/healthz`, `/whoami`. Gunicorn entrypoint. |
| `config.py` | Every environment variable, in one place |
| `models.py` | Read-only mirror of the four tables this reads |
| `scoring.py` | Verbatim copy of the main app's `app/services/watchlist.py` (goodness score) |
| `data.py` | The read queries behind every tool and endpoint |
| `auth.py` | Bearer token resolution shared by both surfaces |
| `mcp_endpoint.py` | `POST /mcp`: JSON-RPC, tool definitions, dispatch |
| `oauth.py` | OAuth 2.1: discovery, registration, authorize, token |
| `rest_api.py` | `GET /api/v1/...` |
| `check_drift.py` | Dev check that the mirrors still match the main app |

## Security notes

The OAuth endpoints are on a public URL, so the approval page is written to be
read carefully before anyone types a password into it:

- **It names the client that actually registered, and the address the access
  would be sent to.** Anyone can register a client, and a registered name is
  just text the registrant chose. So the page also shows the destination,
  which is the part an attacker cannot fake. A callback outside
  `claude.ai` / `claude.com` raises a visible warning.
- **Failed sign-ins are throttled.** Five failures within 15 minutes lock the
  form for 15 minutes, and a correct password is refused while locked.
- Set `MCP_OAUTH_ALLOW_DYNAMIC_REGISTRATION=0` once connected if you want to
  stop accepting new client registrations altogether.

Access tokens last an hour and refresh tokens 30 days. Rotating
`MCP_SECRET_KEY`, or changing the app login, revokes all of them at once. That
is the kill switch if a token is ever exposed.

## Local development

```bash
cd mcp
pip install -r requirements.txt
cp .env.example .env      # point DATABASE_URL at the main app's database
python server.py          # http://localhost:8000
```

To read the main app's local SQLite database, point `DATABASE_URL` at it with an
absolute path, e.g. `sqlite:///C:/path/to/Lifestyle_App/instance/local.db`.
(Relative SQLite paths resolve inside this folder's own `instance/`.)

If you change a model in `app/models.py` or retune the score in
`app/services/watchlist.py`, mirror the change here and confirm with:

```bash
python mcp/check_drift.py    # from the repo root, with the main app's requirements installed
```
