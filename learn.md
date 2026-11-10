# Start from zero: how to understand this codebase

You do not need to understand every file. A codebase is like a city: you learn it street by street, not by memorizing every building.

This project is three programs talking to each other:

```text
1. Chrome extension       → collects option data from Sensibull
2. Backend (Python)       → validates, archives, scans, stores, serves
3. Two websites           → admin console and user signal app
```

The database is inside the backend story. The websites never talk to the database directly.

---

## 1. Six words to learn first

| Word | Plain meaning | In this project |
|---|---|---|
| File | A page of instructions | `content.js`, `scan_service.py` |
| Function | A named recipe that does one job | `scanSymbol()`, `publish_signal()` |
| Variable | A labelled box holding a value | `scanId`, `symbol`, `price` |
| API | A waiter: you ask, it brings data | `/api/v1/signals/active` |
| Server | A program always waiting for requests | FastAPI on port `8000` |
| Database | A permanent ledger of records | SQLite now, PostgreSQL in production |

Two more:

- **Frontend**: what you see and click.
- **Backend**: the hidden program that enforces rules and stores data.

---

## 2. The project as one story

```text
You open Sensibull
        ↓
content.js reads option-chain numbers
        ↓
background.js builds a CSV and uploads it to the backend
        ↓
backend keeps the original CSV on disk
        ↓
backend runs the scanner and stores only filtered candidates
        ↓
admin approves a candidate and publishes a signal
        ↓
user app reads that signal through the API
        ↓
FYERS worker later updates the live price
```

The most important sentence:

> **The CSV is the truth. The database stores decisions and filtered results, not raw option data.**

That is why the archive exists and why PostgreSQL does not hold strike-by-strike tables.

---

## 3. What each folder does

| Folder/file | Job | Learn this after |
|---|---|---|
| `manifest.json` | Tells Chrome what the extension is allowed to do | Nothing |
| `content.js` | Runs inside Sensibull, fetches option data | JS basics |
| `background.js` | Coordinates scan, CSV, upload, schedules | JS functions + async |
| `popup.*` | Extension UI | HTML/CSS |
| `backend/app/main.py` | Starts the backend server | Python basics |
| `backend/app/models/` | Describes database tables | SQL basics |
| `backend/app/schemas/` | Describes API request/response shapes | JSON |
| `backend/app/api/` | Defines URLs and permissions | HTTP |
| `backend/app/services/` | Business rules and transactions | Functions + DB |
| `backend/app/db/` | Opens database connections | SQL + sessions |
| `admin/` | Admin Next.js website | React/TypeScript later |
| `user/` | User Next.js website | React/TypeScript later |
| `docker-compose.yml` | Runs backend + PostgreSQL together | Deployment later |

Do not try to learn all of these in one week. Pick one layer.

---

## 4. How to read the code, in order

Read for **what goes in and what comes out**, not for every line.

### Step 1: `manifest.json`

This is the extension’s table of contents. It says:

- permission to read Sensibull
- permission to store data
- which script runs inside the page
- which script runs in the background

If you understand this file, you understand the extension’s shape.

### Step 2: `content.js`

Find these functions:

- `scanSymbol(symbol)` → one symbol in, one data object out.
- `runScanner(options)` → many symbols in, all results out.

Ask only:

1. Where does the data come from?
2. What shape is it?
3. Where does it go next?

Do not worry about retries or progress yet.

### Step 3: `background.js`

Find `orchestrateScan`. This is the coordinator:

```text
create scan on backend
    ↓
ask content script to scan
    ↓
build CSV
    ↓
upload CSV
    ↓
mark scan complete
```

If the upload fails, it downloads the CSV locally. This is a reliability decision, not random code.

### Step 4: `backend/app/main.py`

This is the backend’s front door. It:

- starts FastAPI
- registers URLs
- creates the admin account on first boot
- starts the price tracker

The key idea: **entry point**. Every program has one place where execution begins.

### Step 5: `backend/app/models/scan.py` and `signal.py`

A model is a Python class that describes a table.

```text
class ScanCandidate  →  table scan_candidates
    symbol           →  column symbol
    direction        →  column direction
    score            →  column score
```

One class instance = one row. One class = one table.

Do not memorize the classes. Learn the relationships:

```text
one scan → many candidates
one candidate → zero or one signal
one signal → many price observations
```

### Step 6: `backend/app/api/collector.py`

An API file maps a URL to a function.

```text
POST /collector/scans/{id}/csv
    → upload_csv()
        → scan_service.handle_csv_upload()
```

The route should be thin. It validates HTTP details and delegates the real work.

### Step 7: `backend/app/services/scan_service.py`

This is the heart of the data pipeline:

```text
save CSV
commit archive metadata
scan CSV
insert candidates
commit
```

Read it as a numbered recipe. That is exactly what a service is.

### Step 8: Signals

Read:

- `backend/app/api/signals.py` — what the user app can ask for
- `backend/app/services/signal_service.py` — how publishing works
- `backend/app/workers/price_tracker_worker.py` — how live prices update

The workflow:

```text
APPROVED candidate
    → publish
    → INSERT signal
    → UPDATE candidate to PUBLISHED
    → INSERT audit log
    → COMMIT
```

### Step 9: Frontends, last

Only after the backend makes sense:

```text
admin/lib/api.ts       → how the browser calls the backend
admin/app/.../page.tsx → screen logic
user/app/.../page.tsx  → read-only signal screens
```

A page does three things:

1. asks the API for data
2. stores the response in a variable/state
3. draws HTML from it

That is 80% of frontend code.

---

## 5. Survival kit: the syntax you will see

### JavaScript

```js
const symbol = "WIPRO";          // constant value
let count = 0;                   // changeable value

function add(a, b) {             // a recipe
  return a + b;
}

async function load() {          // a recipe that waits
  const response = await fetch(url);
}

const data = { symbol, price };  // object
const list = [1, 2, 3];          // array

if (count > 0) { ... }           // condition
try { ... } catch (error) { ... } // error handling
```

`await` means “pause this function until the slow thing finishes.” Network calls and database calls are slow.

### Python

```python
def add(a: int, b: int) -> int:   # a recipe
    return a + b

if count > 0:                     # indentation matters
    print("yes")

try:
    do_work()
except Exception as error:
    print(error)
```

Python reads almost like English. Focus on function names and indentation.

### JSON

JSON is how the browser and server exchange data:

```json
{
  "symbol": "WIPRO",
  "direction": "LONG",
  "current_ltp": null
}
```

`null` means “no value exists.” In your app, it honestly means “no live price observed yet.”

### SQL

SQL is how you talk to the database directly:

```sql
SELECT symbol, status FROM published_signals;
INSERT INTO published_signals (...) VALUES (...);
UPDATE scan_candidates SET status = 'APPROVED' WHERE id = ...;
```

Table = sheet. Row = record. Column = field.

---

## 6. The database, explained simply

Think of a spreadsheet:

```text
published_signals
-------------------------------------------------
symbol   direction  status  entry   current_ltp
WIPRO    LONG       ACTIVE  196.22  NULL
SWIGGY   SHORT      ACTIVE  189.08  NULL
```

- A **table** is a sheet.
- A **row** is one record.
- A **column** is one field.
- A **primary key** is the unique ID of a row.
- A **foreign key** is a pointer to another table’s row.
- An **index** is a book index: it makes lookups faster.

An **ORM** like SQLAlchemy lets Python say:

```python
signal = PublishedSignal(symbol="WIPRO", ...)
db.add(signal)
db.commit()
```

and translates it into `INSERT`/`UPDATE` SQL.

A **session** is your workspace:

```text
load objects → change them → commit or rollback → close
```

A **migration** is version control for the database structure. `create_all()` is fine for local development; production uses Alembic so schema changes are reproducible.

Current local database: `backend/run-dev.db`.  
Production database: PostgreSQL through Docker Compose.

---

## 7. Trace one real request

### User opens “Active Signals”

```text
Browser sends:
GET /api/v1/signals/active

FastAPI:
checks JWT token
opens a database session
runs SELECT on published_signals WHERE status='ACTIVE'

Database:
returns rows

FastAPI:
converts rows to JSON

Browser:
receives items
React renders cards
```

If the response has `current_ltp: null`, the UI shows `UNKNOWN`. Nothing is broken. It is correct because no live quote exists.

### Admin clicks “Publish”

```text
POST /api/v1/admin/candidates/{id}/publish

FastAPI:
checks admin role
checks candidate is APPROVED
validates prices
inserts published_signal
inserts initial price history
updates candidate to PUBLISHED
inserts audit log
commits

User app:
next refresh reads the new ACTIVE signal
```

The same database is read by both apps. That is why “this is connected to db” feels true — it is one backend and one ledger.

---

## 8. How to inspect your own system

### API documentation

Open:

```text
http://127.0.0.1:8000/docs
```

You can see every endpoint and even try them with a token.

### Database

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('backend/run-dev.db'); print(c.execute('select symbol,status,current_ltp from published_signals').fetchall())"
```

### Browser

Open DevTools → Network → click a page → inspect the request and JSON response.

### Logs

Backend logs are in the terminal or `%TEMP%\sensibull-backend.log`.

### The debugging rule

```text
UI wrong → check Network
Network wrong → check backend logs
Backend wrong → query the database
Database wrong → check service transaction
```

Always move one layer at a time.

---

## 9. What to learn next: a realistic order

Do not learn JavaScript, Python, SQL, React, Docker and FastAPI simultaneously. That is how beginners quit.

### Week 1 — Programming and the web

- Variables, functions, arrays, objects, `if`, loops
- JSON
- HTTP: GET, POST, status codes
- Browser DevTools Network tab
- Git basics: status, diff, add, commit

Practice: open the running user app and use DevTools to watch `/signals/active`.

### Week 2 — SQL and databases

- tables, rows, columns
- primary key, foreign key
- `SELECT`, `INSERT`, `UPDATE`, `WHERE`, `JOIN`
- indexes and why they exist
- transactions: commit and rollback

Practice: query `run-dev.db`, then join `scan_candidates` and `published_signals`.

### Week 3 — Python and the backend

- Python functions, classes, dictionaries
- FastAPI routes: path, body, response
- Pydantic validation
- SQLAlchemy models and sessions
- dependency injection (`Depends`)

Practice: trace `POST /collector/scans/{id}/csv` from route to service to database.

### Week 4 — JavaScript and the frontend

- HTML/CSS basics
- React components and state
- `fetch` and `useEffect`
- Next.js pages
- auth tokens and protected pages

Practice: change one label in the user app, then add a small filter.

After that:

- testing with pytest
- Docker
- authentication and security
- observability
- concurrency and idempotency

---

## 10. Beginner mistakes to avoid

1. **Reading every file.** Read one flow end-to-end instead.
2. **Copying code without changing it.** Change one line, observe the result.
3. **Ignoring error messages.** The message usually names the file and line.
4. **Learning frameworks before fundamentals.** HTTP and SQL matter more than Next.js.
5. **Assuming the database is magic.** Query it directly.
6. **Trying to become senior in a month.** Seniority is accumulated debugging and design decisions.
7. **Asking AI for code before predicting what the code should do.**

---

## 11. Your first practical exercise

Do this without changing functionality:

1. Open the user app at `http://localhost:3001`.
2. Open DevTools → Network.
3. Log in and navigate to Active Signals.
4. Find the request to `/api/v1/signals/active`.
5. Write down:
   - request method
   - status code
   - one field from the response
   - why `current_ltp` is `null`

Then answer these in your own words:

1. What does `content.js` produce?
2. What does the backend do with the CSV before inserting candidates?
3. Why do the websites not connect directly to the database?
4. What is the difference between a database table and a Python model?
5. What does `commit()` mean?

Reply with your answers. I will correct them and then take you through the first file, line by line, at beginner pace.
