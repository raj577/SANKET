# SANKET — Market Signals Platform

## Overview
SANKET is an end-to-end market-data and signal-management platform. It combines a Chrome extension for capturing option-chain data from Sensibull, a FastAPI backend, and two separate Next.js web apps (admin and user). The system archives every data snapshot, runs a server-side, versioned scan pipeline, stores candidates and published signals, tracks live prices, and presents date-wise views to both administrators and end users.

The proprietary stock-filtering methodology is intentionally excluded from this summary.

## Architecture
- **Chrome extension (Manifest V3)** — captures option-chain snapshots, manages watchlists and schedules, exports CSV, uploads results to the backend, and supports optional Telegram/Google Sheets integrations.
- **Backend (FastAPI)** — authentication, collector ingestion, scan lifecycle, candidate review, signal publication, audit logging, market-data tracking, CSV archiving, and admin APIs.
- **Admin panel (Next.js)** — dashboards, scans, candidates, signals, users, archives, audit log, settings, and provider connections.
- **User panel (Next.js)** — overview, active signals, history, and signal detail with live price context.
- **Database** — PostgreSQL on Neon.
- **Market data** — FYERS REST APIs (quotes, option chain, OAuth) and Kotak Neo REST + SFeed WebSocket (live LTPs), behind a provider abstraction.
- **Deployment** — Google Cloud Run (backend, admin, user), Secret Manager, Neon; Docker images and Next.js standalone builds. Also runnable on a VPS or local machine.

## Tech Stack
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, pandas/NumPy, httpx, PyJWT, passlib, WebSockets, pytest.
- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, server-side BFF proxies, HttpOnly cookie sessions.
- **Extension:** Vanilla JS, Chrome MV3 service worker, content scripts, `chrome.storage`, alarms, downloads, notifications.
- **Data providers:** FYERS v3 API, Kotak Neo API/SDK.
- **Infra:** Docker, Cloud Run, Artifact/Cloud Build, Secret Manager, Neon Postgres, optional S3/R2 storage.
- **Messaging:** WebSocket broadcasts to panels; Telegram hooks for the extension.

## Key Features
- Collector-token ingestion with archived source files and SHA-256 checksums.
- Versioned, reproducible scan runs with persisted configuration fingerprints.
- Admin-run option-chain scans directly from FYERS or Kotak, bypassing the browser extension.
- Candidate review workflow (approve/reject/publish), signal lifecycle, and audit trail.
- Live LTP tracking with freshness states (LIVE/DELAYED/STALE/UNKNOWN) and automatic target/stop-loss closure.
- Date-wise admin and user views, percentage movement from signal-time price to latest price, and target-reached indicators.
- Separate admin and user panels with role-based access and date/status/symbol filters.
- Daily TOTP/MPIN and OAuth session handling for market-data providers.

## Challenges Faced
- **Third-party data reliability:** the source is a JavaScript SPA with changing endpoints, session requirements, and rate limits, so ingestion had to be resilient and archive-first.
- **Provider heterogeneity:** FYERS and Kotak expose different auth models, symbol formats, instrument identifiers, and response shapes. Kotak's option-chain payload also labels price change under OI fields, requiring careful validation and normalization.
- **Live-stream lifecycle:** Kotak's WebSocket needs a TOTP/MPIN session, resubscription when new signals are published, reconnect/re-auth after drops, and throttled database writes. Running multiple backend instances would open competing provider sessions, so deployment is constrained to a single worker/instance.
- **Storage coupling:** the original scan pipeline required an archived CSV before filtering. Cloud deployments forced a choice between durable object storage and ephemeral disks; the design now supports provider-generated scans while keeping archive semantics.
- **Timezone and date boundaries:** all persisted timestamps are UTC while business-day filtering and reporting are IST, requiring explicit half-open day windows.
- **Proxy and security issues:** HttpOnly cookie sessions, same-origin checks behind Cloud Run, CORS preflights, collector-token rotation, and extension host permissions each caused deployment-specific failures that had to be diagnosed and fixed.
- **Extension distribution:** shipping a zero-setup extension meant baking the backend origin and a revocable collector token, migrating old localhost configurations, and balancing convenience against credential exposure.
- **Market-state edge cases:** holidays and closed sessions produce identical or zero-change snapshots, so "no candidates" can be correct behavior rather than a failure; freshness and movement semantics had to reflect actual observations only.
- **Cost/ops trade-offs:** always-on background tracking conflicts with scale-to-zero hosting; Cloud Run required minimum instances and no CPU throttling, while a small VPS required swap and single-worker discipline.

## Verification
- 37 backend tests covering auth, ingestion, scan lifecycle, date filters, signal movement, target closure, and provider parsing.
- TypeScript type-checking for both Next.js apps.
- Live smoke tests against the deployed API, including auth, admin endpoints, validation errors, collector authentication, and live provider status.
