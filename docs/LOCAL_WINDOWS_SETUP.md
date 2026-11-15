# Local Windows 11 Setup — FYERS Data-Only Backend

This guide brings the FastAPI backend up on a Windows 11 machine with
PowerShell, using the **official FYERS OAuth v3 flow** and encrypted token
storage. It covers a *local* environment only; the GCP deployment is a separate
phase (see [Local vs GCP](#14-local-vs-gcp)).

Network calls are **market-data only**. The integration never places, modifies
or cancels orders, and never automates the FYERS username/password/TOTP login.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Windows 11 + PowerShell 5.1 or 7.x | Commands below are PowerShell. |
| Python 3.12 (64-bit) | `py -3.12 --version`. The project was verified on 3.12.6. |
| Git | Optional, but the project is a git repository. |
| Docker Desktop | Optional — only if you want local PostgreSQL. |
| PostgreSQL 16 | Optional — a native install works too. |
| A FYERS account + API app | Data-only ("Individual — Non-Trading") app, see §7. |

A local PostgreSQL server is **not** required: development can run on SQLite
(§5). Production must use PostgreSQL.

---

## 2. Python and virtual environment

From the repository root (the folder containing `backend/`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
pip install -r backend\requirements-dev.txt
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

> Never commit `.venv/`. It is already in `.gitignore`.

Sanity check:

```powershell
python --version              # 3.12.x
python -c "import fastapi, sqlalchemy, httpx, jwt, cryptography; print('ok')"
```

---

## 3. Project layout (what matters locally)

```
backend/
  app/main.py                 FastAPI entry point (app.main:app)
  app/core/config.py          Settings loaded from environment/.env
  app/market_data/
    fyers_auth.py             OAuth state, login URL, code exchange
    fyers_token_store.py      Fernet-encrypted token file + status
    fyers_client.py           Read-only quotes/history/option chain/client
    provider.py               Market-data provider selection
  app/api/market.py           /market/fyers/{login-url,callback,status,exchange}
  scripts/verify_fyers.py     Read-only live data verification
  migrations/                 Alembic migrations
  storage/                    Local archives + encrypted token (git-ignored)
```

---

## 4. Environment variables

Copy the template **only if** `backend/.env` does not already exist:

```powershell
cd backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Never commit `.env` and never paste its contents into chat, docs or tickets.
`.env` is already in `.gitignore`.

Required names (values are yours to generate):

| Variable | Purpose |
|---|---|
| `FYERS_APP_ID` | App ID from the FYERS dashboard, for example `ABC12345-100`. |
| `FYERS_SECRET_KEY` | App secret from the FYERS dashboard (shown once). |
| `FYERS_REDIRECT_URI` | `http://localhost:8000/api/v1/market/fyers/callback` |
| `FYERS_TOKEN_FILE` | `storage/fyers_token.bin` |
| `FYERS_TOKEN_ENCRYPTION_KEY` | Fernet key that encrypts the token at rest. |
| `FYERS_OAUTH_STATE_TTL_SECONDS` | Signed OAuth state lifetime, default `300`. |
| `MARKET_DATA_PROVIDER` | `fyers` or `kotak`. |
| `SCANNER_DATA_PROVIDER` | `fyers` or `kotak` (admin OI scan). |
| `JWT_SECRET` | Signing key for app JWTs **and** the OAuth state. |
| `DATABASE_URL` | Local database URL (§5). |
| `ENVIRONMENT` | `development` locally, `production` on GCP. |
| `DEBUG` | `false` (keep `false`; debug traces can leak data). |

`MARKET_DATA_PROVIDER` selects the LTP-tracking provider and
`SCANNER_DATA_PROVIDER` selects the option-chain provider for the admin OI scan.
They are independent: for example a `.env` with `MARKET_DATA_PROVIDER=kotak`
(websocket LTP tracking) and `SCANNER_DATA_PROVIDER=fyers` still uses the FYERS
OAuth token for scans. `/api/v1/market/status` reports the active provider.

Generate the secrets locally:

```powershell
# JWT secret
python -c "import secrets; print(secrets.token_urlsafe(48))"

# FYERS token encryption key (run from backend/)
python -m app.cli generate-fyers-key
```

Paste the values into `backend/.env`. Keep `FYERS_TOKEN_ENCRYPTION_KEY` stable:
if it changes, the stored token can no longer be decrypted and you must log in
again. There is **no plaintext fallback** — without the key, token storage is
refused.

---

## 5. Database configuration (exact local steps)

The repository's `backend/.env` may point `DATABASE_URL` at a shared/cloud
PostgreSQL instance. **Do not use that for local development.** Pick one of the
options below and set `DATABASE_URL` for your local shell.

### Option A — SQLite (fastest, no server)

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./run-dev.db"
```

Environment variables take precedence over `.env` for the current PowerShell
session only. Development startup creates tables automatically (see §9).

### Option B — PostgreSQL in Docker

`docker-compose.yml` defines the `db` service but does not publish port 5432 to
the host. Add a mapping if you want to connect from Windows:

```yaml
    ports:
      - "5432:5432"
```

Then:

```powershell
docker compose up -d db
cd backend
$env:DATABASE_URL = "postgresql+psycopg://sensibull:sensibull@localhost:5432/sensibull"
python -m alembic -c alembic.ini upgrade head
```

### Option C — Native PostgreSQL 16

1. Install PostgreSQL 16 and remember the `postgres` superuser password.
2. Create the role and database:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE ROLE sensibull LOGIN PASSWORD 'sensibull';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE sensibull OWNER sensibull;"
```

3. In `backend`:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://sensibull:sensibull@localhost:5432/sensibull"
python -m alembic -c alembic.ini upgrade head
```

Verify connectivity:

```powershell
python -c "from app.db.session import get_engine; from sqlalchemy import text; print(get_engine().connect().execute(text('select 1')).scalar())"
```

> Local development must never point at the production/cloud database, and
> production credentials must never be used locally.

---

## 6. Local files the backend writes

| Path | Contents | Safe to commit? |
|---|---|---|
| `backend/storage/fyers_token.bin` | Fernet-encrypted FYERS token + metadata | **No** (`storage/` is ignored) |
| `backend/storage/sensibull/` | Published scan CSV archives | No |
| `backend/run-dev.db` | SQLite dev database | No (`*.db` is ignored) |

---

## 7. FYERS dashboard configuration

1. Sign in to FYERS and open the **API Dashboard**
   (My Account → API → *Create App*).
2. Create an application of type **Individual — Non-Trading** (a data-only app).
   The platform only needs market data; it does not request trading
   permissions, and this backend never calls order APIs.
3. Set **Redirect URL** to exactly:

   ```
   http://localhost:8000/api/v1/market/fyers/callback
   ```

   It must match `FYERS_REDIRECT_URI` byte for byte — scheme, host, port, path,
   no trailing slash. A mismatch produces an error page on the FYERS side or an
   invalid-redirect rejection.
4. Copy the **App ID** (format `XXXXXXXX-100`) and the **App Secret** into
   `backend/.env` as `FYERS_APP_ID` / `FYERS_SECRET_KEY`.
5. Check which API plan your account has. Data endpoints (quotes, history,
   option chain) are metered/subscription-bound; if they are not enabled, the
   OAuth login still works but data calls return FYERS errors. Do not enable
   trading permissions for this project.

Notes:

* The app secret is shown once; store it only in `.env` (or a secret manager
  later), never in git or chat.
* `localhost` redirect URLs are for development. For GCP you will register an
  HTTPS redirect URL on a publicly reachable host.

---

## 8. Starting the application

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./run-dev.db"   # or your PostgreSQL URL from §5
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The entry point is `app.main:app`. On startup in non-production environments the
backend creates missing tables, seeds default settings and bootstraps the admin
account from `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` if that email
does not exist yet.

Verify:

| Check | Command |
|---|---|
| Health | `Invoke-RestMethod http://127.0.0.1:8000/health` |
| OpenAPI docs | open `http://127.0.0.1:8000/docs` |
| Database | health returns `"database":"ok"` |

`/health` reports `"status":"degraded"` if the database is unreachable.

---

## 9. Admin login

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType "application/json" `
  -Body (@{ email = "you@example.com"; password = "your-password" } | ConvertTo-Json)

$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

If the bootstrap admin already existed, create another one explicitly:

```powershell
python -m app.cli create-admin --email you@example.com --password "a-long-password"
```

---

## 10. Browser authentication (OAuth)

1. Request the authorization URL as an admin. The response contains a **signed,
   short-lived** `state` (`FYERS_OAUTH_STATE_TTL_SECONDS`, default 5 minutes):

   ```powershell
   $loginUrl = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/market/fyers/login-url -Headers $headers
   $loginUrl.url
   ```

2. Open that URL in the browser and complete the normal FYERS login (including
   whatever MFA FYERS asks for). The backend never sees your FYERS password.

3. FYERS redirects to
   `http://localhost:8000/api/v1/market/fyers/callback?auth_code=...&state=...`.
   The backend then:

   * rejects the request if the state is missing, expired, tampered with, or
     not issued by this application;
   * rejects FYERS-reported errors (`s=error`);
   * exchanges the one-time code **server-side** with the app hash;
   * encrypts the access token with Fernet and writes
     `storage/fyers_token.bin`;
   * shows an HTML confirmation page containing only the expiry time.

   The access token is never written to the page, the URL, the logs or an API
   response.

4. The callback is an unauthenticated redirect (the browser cannot send the
   admin bearer token), which is why the signed `state` is required. Each state
   is short-lived and each authorization code is single-use: refreshing the
   callback page shows a "may have expired, or it may have already been used"
   message instead of storing anything twice.

The admin UI at *Settings → **FYERS data connection*** performs steps 1–2 for you.
The card is independent of `MARKET_DATA_PROVIDER`, because the admin OI scan
uses `SCANNER_DATA_PROVIDER`; a Kotak LTP setup with FYERS scans still shows the
FYERS login state. It renders:

* status badge — *Connected*, *Expires soon*, *Re-login required*, or *Not connected*;
* token validity (`Valid until …` in IST plus a countdown), last login time and source;
* whether the encryption key and app credentials are configured;
* the registered redirect URI;
* an amber warning when `FYERS_TOKEN_ENCRYPTION_KEY` or the app credentials are missing;
* an amber warning when the daily token has expired or expires within 15 minutes.

The card refetches `/market/fyers/status` when the tab regains focus, so
returning from the FYERS login tab flips the badge without a page reload. The
legacy "paste a code" form still works
(`POST /api/v1/market/fyers/exchange?code=...`, admin only). The access token is
never rendered in the UI.

### Callback verification

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/market/fyers/status -Headers $headers
```

Expected after a successful login:

```json
{
  "token_present": true,
  "token_valid": true,
  "reauth_required": false,
  "encryption_configured": true,
  "credentials_configured": true,
  "expires_at": "2026-11-16T00:30:00+00:00",
  "authenticated_at": "2026-11-15T12:00:00+00:00",
  "seconds_remaining": 43200,
  "source": "oauth_callback"
}
```

The payload never contains the access token, by design.

### CLI status check

```powershell
python -m app.cli fyers-status
```

Prints the same secret-free status (exit code `1` when no token is stored).

---

## 11. Live market-data verification

Read-only checks against the real FYERS API — no orders are placed:

```powershell
cd backend
python scripts\verify_fyers.py
python scripts\verify_fyers.py --symbol NSE:RELIANCE-EQ --chain-symbol NSE:NIFTY50-INDEX
```

It reports PASS/FAIL for: encrypted-token status, authenticated profile, live
quote, daily historical candles, and an option chain. Exit code `0` means all
checks passed; `2` means no usable token (log in first).

Manual equivalents:

```powershell
# Pull the encrypted token in-process only; never echo it
python -c "from app.market_data.fyers_client import FyersClient; c=FyersClient(); print(c.ltp_map(['NSE:NIFTY50-INDEX','NSE:SBIN-EQ'])); print(len(c.history('NSE:SBIN-EQ', range_from='1700000000', range_to='1700600000').get('candles',[])))"
```

Scanner behaviour with FYERS data is exercised by the admin OI scan
(`POST /api/v1/admin/scans/oi` with `{"provider":"fyers","symbols":[...]}`).

---

## 12. Tests

```powershell
cd backend
python -m compileall -q app
pytest -q
```

FYERS OAuth tests run fully offline: the token endpoint is monkeypatched, a
throwaway Fernet key and temporary token path are used, and no live credentials
are read. Tests cover state signing/expiry/tampering, encrypted storage,
expiry reporting, missing credentials, invalid callbacks, duplicate/failed
callbacks and admin-only protection.

---

## 13. Common errors and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `Activate.ps1 cannot be loaded` | Execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `/health` → `degraded` | DB unreachable | Check `DATABASE_URL`; for SQLite use `sqlite:///./run-dev.db` |
| `ModuleNotFoundError: cryptography` | deps not installed | `pip install -r requirements.txt` |
| `401` on `login-url` / `status` | Missing/expired admin JWT | Log in again (`/api/v1/auth/login`) |
| `403` on `login-url` / `status` | Role is not `ADMIN` | Use an admin account |
| `422` on `/auth/login` or `create-admin` | Email uses a reserved domain (`.test`, `.local`, `.invalid`, `localhost`) | Use a normal domain such as `you@example.com` |
| `503 fyers_not_configured` | `FYERS_APP_ID` empty | Fill `.env`, restart uvicorn |
| FYERS page: redirect URI mismatch | Dashboard URL ≠ `FYERS_REDIRECT_URI` | Make them identical, including port and path |
| Callback: "login link expired or invalid" | State older than the TTL, or tampered | Start the login again from the admin panel |
| Callback: "may have expired, or it may have already been used" | Authorization code already redeemed | Start the login again |
| "FYERS authorised, but the token was not stored" | `FYERS_TOKEN_ENCRYPTION_KEY` missing/invalid | Generate one (§4) and log in again |
| "cannot be decrypted; key changed or file corrupt" | Key rotated | Re-login; optionally delete `storage/fyers_token.bin` |
| "Legacy plaintext token found and ignored" | Old `storage/fyers_token.json` exists | Delete it and log in again |
| Data calls fail with `401` | Daily FYERS token expired | Repeat the browser login |
| Data calls fail with `Invalid appIdHash` | Wrong `FYERS_SECRET_KEY` | Re-copy the app secret |
| Data calls fail with permission/plan errors | API plan lacks data access | Check the FYERS API plan |

---

## 14. Local vs GCP

| Concern | Local (Windows) | GCP (later phase) |
|---|---|---|
| Redirect URL | `http://localhost:8000/api/v1/market/fyers/callback` | HTTPS URL on the deployed host; register it on the FYERS app |
| Database | SQLite or local PostgreSQL | Cloud SQL PostgreSQL; run `alembic upgrade head` in the deploy step |
| Secrets | `backend/.env` | Secret Manager → runtime env vars; never in the image or git |
| `JWT_SECRET` | Generated locally | Stable, ≥32 chars, shared across instances |
| `FYERS_TOKEN_ENCRYPTION_KEY` | In `.env` | Secret Manager; identical on every instance that reads the token |
| Token file | `backend/storage/fyers_token.bin` | Persistent volume or database row — a container's local disk is ephemeral and resets on redeploy |
| Server | `uvicorn --reload`, 127.0.0.1 | Container/`uvicorn` workers behind HTTPS, no `--reload` |
| `ENVIRONMENT` | `development` | `production` (turns off `/docs`, `/redoc`, `/openapi.json` and enables stricter checks) |
| TLS | Not used | Required; HSTS enabled automatically in production |

Production checklist items that stay open for the GCP phase:

1. Encrypt-and-persist the FYERS token somewhere multi-instance safe (shared
   volume or a table row encrypted with the same key).
2. Put `JWT_SECRET` and `FYERS_TOKEN_ENCRYPTION_KEY` in Secret Manager.
3. Register the production redirect URI on the FYERS app.
4. Run Alembic migrations instead of `create_all`.
5. Rotate the local dev `JWT_SECRET`/admin bootstrap password away from anything
   reused in production.
