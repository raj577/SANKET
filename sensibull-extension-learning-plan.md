# Sensibull OI Scanner — Complete Learning Plan

> **Audience:** Junior developer new to Chrome Extensions, browser APIs, and advanced JS/TS.
> **Goal:** Transform this 4-file project into an end-to-end learning experience covering every concept, pattern, and design decision.

---

## 1. WHAT IS A CHROME EXTENSION?

### Concept
A Chrome Extension is a small program that lives inside your browser. It can read web pages, modify them, store data, and talk to servers — all without being a full website.

### Real-World Analogy
Think of a browser as an apartment building. Websites are the tenants in each apartment. A Chrome Extension is the building superintendent — it has keys to every apartment, can enter when needed, knows what's happening in common areas, and coordinates between apartments. But it can only enter apartments the building owner (the user) has approved.

### Technical Explanation
Chrome Extensions are packaged web applications — HTML, CSS, JavaScript — that run in Chrome's extension runtime, not in a normal webpage context. They have their own:
- **Origin:** `chrome-extension://<id>/`
- **Process model (MV3):** Service workers, not persistent background pages
- **Security boundary:** Sandboxed per-extension
- **API surface:** `chrome.*` APIs not available to regular web pages

### What Makes Extensions Special
| Feature | Regular Web Page | Chrome Extension |
|---------|-----------------|------------------|
| Can read arbitrary tabs | No | Yes (with permission) |
| Access to `chrome.*` APIs | No | Yes |
| Runs when browser starts | No | Yes |
| Persistent storage APIs | localStorage | `chrome.storage` |
| Cross-origin requests | CORS-restricted | Extended with host_permissions |
| Can modify web pages | No | Yes (content scripts) |

---

## 2. CHROME EXTENSION ARCHITECTURE

### The Four Worlds

Every MV3 extension has up to four "worlds" (JavaScript execution contexts):

```
┌─────────────────────────────────────────────────────┐
│                   CHROME BROWSER                      │
│                                                       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  POPUP   │  │   SERVICE    │  │   OPTIONS     │  │
│  │          │  │   WORKER     │  │   PAGE        │  │
│  │ (lives   │  │ (wakes up   │  │ (settings    │  │
│  │  seconds)│  │  when needed)│  │  UI)          │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
│        │              │                  │            │
│        └──────────────┼──────────────────┘            │
│                       │  chrome.runtime.sendMessage   │
│                       ▼                               │
│  ┌──────────────────────────────────────────────┐    │
│  │            CONTENT SCRIPT                     │    │
│  │  (injected into web.sensibull.com pages)      │    │
│  │  Can read/modify the webpage DOM              │    │
│  └──────────────────────────────────────────────┘    │
│                                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │              WEB PAGE (web.sensibull.com)      │    │
│  │  Normal website — extension cannot touch       │    │
│  │  directly, only through content script         │    │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### This Extension Uses Only 2 Worlds
- **Popup** — the tiny window when you click the extension icon
- **Content Script** — injected into `web.sensibull.com`

There is NO background service worker, NO options page.

---

## 3. THE POPUP

### Concept
When you click the extension icon in Chrome's toolbar, a small HTML page appears. That's the popup. It's just a mini website, but it has access to `chrome.*` APIs.

### Real-World Analogy
The popup is like a remote control. You pick it up (click the icon), press a button (click "Run Scan"), it sends a signal, and then you put it down (popup closes). It has no memory — every time you open it, it's a fresh remote.

### Lifecycle
```
User clicks extension icon
         │
         ▼
  popup.html loads
         │
         ▼
  popup.js executes (DOMContentLoaded)
         │
         ▼
  User interacts / clicks button
         │
         ▼
  Popup closes (user clicks away)
         │
         ▼
  Everything destroyed. Gone.
```

**Critical rule:** A popup dies the moment the user clicks outside it. There is no "running in background." If you start a network request in the popup and the user closes it, the request is cancelled.

### This Extension's Popup
- `popup.html` — 300px wide card with a heading and a "Run Scan" button
- `popup.js` — listens for click, sends message to content script, shows status

---

## 4. THE CONTENT SCRIPT

### Concept
A content script is JavaScript that Chrome injects INTO a web page. It runs in an "isolated world" — it shares the page's DOM but NOT the page's JavaScript variables.

### What It CAN Access
- The page's DOM (HTML elements, text, images)
- `chrome.runtime` messaging APIs
- Chrome extension storage
- The page's cookies (if host permission granted)
- The page's network (it can `fetch()` from the page context)

### What It CANNOT Access
- JavaScript variables/functions defined by the page
- The page's `window` object (unless using `MAIN` world injection)
- Most `chrome.*` APIs (tabs, downloads, etc.)

### Real-World Analogy
A content script is like a health inspector who enters a restaurant. They can see the kitchen (DOM), read the menu (page content), and file a report (sendMessage). But they can't join the kitchen staff (page JS), access the restaurant's bank account (page's window object), or change the ownership (can't access most chrome.* APIs).

### Isolated World Diagram
```
┌──────────────────────────────────────┐
│         WEB PAGE JAVASCRIPT          │
│  window.myVariable = "hello"         │
│  var userData = { ... }              │
│                                      │
│  ┌────────────────────────────────┐  │
│  │  CONTENT SCRIPT (Isolated)     │  │
│  │  window.myVariable → undefined │  │
│  │  document.body → ✅ accessible │  │
│  │  chrome.runtime → ✅ available │  │
│  └────────────────────────────────┘  │
│                                      │
│  Both share: document, DOM Events    │
│  Both separate: JS scope, globals    │
└──────────────────────────────────────┘
```

### This Extension's Content Script
- `content.js` — 675 lines
- **Injected into:** `https://web.sensibull.com/*`
- **Purpose:** Scans ~200 stock symbols by calling Sensibull's internal API, collecting Open Interest data, and downloading a CSV report
- **Listens for:** `runScan` message from popup

---

## 5. THE MESSAGING SYSTEM

### Concept
Chrome's extension messaging lets different parts of the extension talk to each other. Since the popup and content script live in completely separate worlds, they can't call each other's functions directly. Messaging is the bridge.

### One-Time Messages (`sendMessage` / `onMessage`)

```
chrome.runtime.sendMessage(...)     chrome.tabs.sendMessage(...)
         │                                    │
         │  Extension → Extension             │  Extension → Content Script
         │                                    │
         ▼                                    ▼
chrome.runtime.onMessage.addListener(...)
```

**This extension's message flow:**

```
[popup.js]                            [content.js]
    │                                       │
    │  ① User clicks "Run Scan"             │
    │                                       │
    │  ② chrome.tabs.query({active:true})    │
    │     → finds current tab ID            │
    │                                       │
    │  ③ chrome.tabs.sendMessage(            │
    │       tabId,                           │
    │       { action: "runScan" }            │
    │     )                                  │
    │     ─────────────────────────────►     │
    │                                       │  ④ chrome.runtime.onMessage
    │                                       │     fires with request
    │                                       │
    │                                       │  ⑤ runScanner() executes
    │                                       │     (scans all 200 symbols)
    │                                       │
    │                                       │  ⑥ sendResponse({
    │                                       │       message: "Completed X symbols"
    │                                       │     })
    │     ◄──────────────────────────────   │
    │                                       │
    │  ⑦ status.innerText = response        │
    │                                       │
    ▼                                       ▼
```

### The `return true` Pattern (Critical)

When `content.js`'s listener returns `true`, it tells Chrome: "I will call sendResponse later, asynchronously." Without `return true`, Chrome assumes the response is synchronous and closes the message channel immediately. This is one of the most common bugs in extension development.

```javascript
// CORRECT (async response):
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    doAsyncWork().then(result => sendResponse(result));
    return true;  // ← THIS is crucial
});

// WRONG (response never arrives):
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    doAsyncWork().then(result => sendResponse(result));
    // Missing return true → sendResponse is ignored
});
```

---

## 6. MANIFEST.JSON — DEEP DIVE

The manifest is the extension's ID card. Chrome reads this first. Every field matters.

```json
{
    "manifest_version": 3,
    "name": "Sensibull OI Scanner",
    "version": "1.0",
    "permissions": ["activeTab", "downloads"],
    "host_permissions": [
        "https://web.sensibull.com/*",
        "https://oxide.sensibull.com/*"
    ],
    "action": {
        "default_popup": "popup.html"
    },
    "content_scripts": [{
        "matches": ["https://web.sensibull.com/*"],
        "js": ["content.js"]
    }]
}
```

### Field-by-Field Explanation

#### `manifest_version: 3`
**What:** MV3 is the current extension standard (since 2021). MV2 is deprecated.

**Why MV3 replaced MV2:**
| Aspect | MV2 | MV3 |
|--------|-----|-----|
| Background | Persistent page (always running) | Service worker (wakes on demand) |
| Network requests | `webRequest` (can block/modify) | `declarativeNetRequest` (rules) |
| Remotely hosted code | Allowed | Banned (all JS must be packaged) |
| Memory usage | Higher | Lower |
| User privacy | Weaker | Stronger |

**Our extension:** Uses MV3, but has NO service worker — which is fine because the content script handles all logic.

#### `permissions: ["activeTab", "downloads"]`

**`activeTab`:**
- Gives temporary access to the currently active tab when the user invokes the extension (clicks the icon)
- Without it, `chrome.tabs.query()` and `chrome.tabs.sendMessage()` would fail
- **Security note:** `activeTab` is the least-privileged tab permission. It grants access only when the user explicitly acts. Much safer than `"tabs"` which grants permanent access to all tabs.

**`downloads`:**
- Allows starting downloads programmatically
- **Wait — this extension doesn't use `chrome.downloads`.** The content script downloads by creating a blob URL and clicking an `<a>` element. This permission is unused. It's listed but never called. This is a mistake — always request only permissions you actually need.

#### `host_permissions`
- `https://web.sensibull.com/*` — allows content script injection AND cross-origin fetch to this domain
- `https://oxide.sensibull.com/*` — allows the content script's `fetch()` to the Sensibull API server

**Why both are needed:**
- `web.sensibull.com` is where the user browses (content script runs here)
- `oxide.sensibull.com` is Sensibull's backend API (data comes from here)
- Without `oxide.sensibull.com` in host_permissions, the `fetch()` to the API would be blocked by CORS and Chrome's security policy

#### `action.default_popup`
Tells Chrome what HTML file to show when the extension is clicked. Without this, clicking does nothing.

#### `content_scripts`
- `matches: ["https://web.sensibull.com/*"]` — inject `content.js` into every page on web.sensibull.com
- Chrome injects the script automatically on page load
- `run_at` is not specified, defaults to `"document_idle"` (after DOM is ready but before images/iframes finish loading)

---

## 7. FILE-BY-FILE ANALYSIS

---

## 7.1 — `popup.html`

### Purpose
The visual interface. A tiny 300px-wide card with a button.

### Code Walkthrough

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
```

**`<!DOCTYPE html>`** — Tells the browser "this is HTML5." Without it, browsers enter "quirks mode" (older rendering behavior), which breaks modern CSS.

**`<meta charset="utf-8">`** — UTF-8 is the universal character encoding. Without it, non-English characters (like ₹) would display as garbage.

```html
<style>
body { width:300px; padding:15px; font-family:Arial; }
```

**`width:300px`** — Chrome popups don't auto-size. You must set a width. Without this, the popup would be as wide as its content allows, which looks unprofessional.

```css
button { width:100%; padding:10px; margin-top:10px; cursor:pointer; }
```

**`cursor:pointer`** — Changes the mouse to a hand on hover. Good UX. Without it, buttons look like static text.

```html
<button id="scanBtn">Run Scan</button>
<div id="status">Ready</div>
```

**The Button Pattern:**
- Button has an `id` so JavaScript can find it
- Status div shows feedback — starts as "Ready", changes during scanning, shows result after

```html
<script src="popup.js"></script>
```

**Inline vs External:** The script could have been written inline (`<script>...code...</script>`), but external files are better for:
- Separation of concerns
- CSP compliance (MV3 blocks inline scripts by default)
- Maintainability

**Inline scripts DO work in popups** because popups have a relaxed CSP. But it's bad practice.

### Concepts Taught
- HTML5 doctype
- UTF-8 encoding
- CSS sizing for extension popups
- Button click UX patterns
- Script loading (defer vs inline)

---

## 7.2 — `popup.js`

### Purpose
The brain of the popup. Waits for a click, finds the active tab, sends a message, displays the result.

### Line-by-Line

```javascript
document
    .getElementById("scanBtn")
    .addEventListener(
        "click",
        async () => {
```

**Pattern: Event Listener + Async Callback**

JavaScript Concept — **Event Listener:**
An event listener is like a "when this happens, do that" instruction. You register it once, and it fires every time the event occurs.

Real-world analogy: A doorbell. You wire it once. Every time someone presses, it rings. You don't re-wire the doorbell for every visitor.

```javascript
const status = document.getElementById("status");
status.innerText = "Starting...";
```

**`innerText`** — Sets the visible text inside an element. Better than `innerHTML` here because we're setting plain text, not HTML. `innerHTML` would be vulnerable to XSS if we ever inserted user data (though we're not here).

```javascript
try {
    const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true
    });
```

**`chrome.tabs.query()`** — The Tabs API. Asks Chrome: "Which tab is the user looking at right now?"

**Array Destructuring:** `const [tab]` takes the first element of the result array. `chrome.tabs.query` always returns an array (even if empty or single result). If there's no active tab (edge case: browser just opened, no tabs), `tab` would be `undefined`.

**Parameters:**
- `active: true` — only the tab the user is viewing
- `currentWindow: true` — only in the current browser window (not other windows)

```javascript
const response = await chrome.tabs.sendMessage(tab.id, {
    action: "runScan"
});
```

**`chrome.tabs.sendMessage(tabId, message)`** — Sends a message from the popup INTO the content script running in that specific tab. The `tab.id` is the target. Without it, Chrome wouldn't know which website to deliver the message to.

**`await`** — Pauses execution until the content script responds. The content script returns `true` and calls `sendResponse()` later.

**The message format: `{ action: "runScan" }`** — This is a convention. The `action` field tells the receiver "what to do." The receiver checks `if (request.action === "runScan")`.

```javascript
status.innerText = response?.message || "No Response";
```

**Optional Chaining (`?.`):** If `response` is `null` or `undefined`, don't try to access `.message` — just return `undefined`. Prevents "Cannot read property 'message' of undefined" crashes.

**Logical OR (`||`):** If the left side is falsy (empty string, undefined, null, 0), use the right side. Here: if `response` exists but has no `.message`, show "No Response."

```javascript
} catch (e) {
    console.error(e);
    status.innerText = "Open a Sensibull tab first";
}
```

**try/catch:** If any operation inside `try` throws an error, execution jumps to `catch`. The most common errors here:
- No tabs open → `tab` is undefined → `tab.id` throws
- Content script not injected → `sendMessage` fails (no listener)
- User is on a non-Sensibull page → content script isn't there

**`console.error(e)`** — Logs the actual error to the console (developer tools). Good debugging practice — the user sees a friendly message, but you can debug with the real error.

### Data Flow
```
User Click
    │
    ▼
chrome.tabs.query({active:true})  →  [Tab Object]
    │
    ▼
chrome.tabs.sendMessage(tab.id, {action:"runScan"})
    │
    ▼  (crosses into content script world)
    │
content.js chrome.runtime.onMessage fires
    │
    ▼
runScanner() executes (scans 200 symbols)
    │
    ▼
sendResponse({message: "Completed 200 symbols"})
    │
    ▼  (crosses back into popup world)
    │
status.innerText = "Completed 200 symbols"
```

### Production Concern: No Loading State Between Symbols
The popup shows "Starting..." then waits for ALL 200 symbols to finish before showing "Completed 200 symbols." If the scan takes 3+ minutes (200 symbols × 1 second delay each), the user sees "Starting..." for the entire time. No progress indicator. A better approach would be progress updates via a port (long-lived connection) or periodic messages.

### Refactoring Opportunity
The popup lacks error handling for the case where `tab` is undefined (no active tabs). Currently it would throw `Cannot read property 'id' of undefined`. Adding:
```javascript
if (!tab) {
    status.innerText = "No active tab found";
    return;
}
```
...would be more graceful.

---

## 7.3 — `content.js`

### Purpose
The workhorse. Contains:
1. A hardcoded list of ~200 stock symbols
2. A function to categorize option strikes (ATM/ITM/OTM for both CE and PE)
3. A function to fetch OI data from Sensibull's API for one symbol
4. A function to scan ALL symbols sequentially
5. A function to generate and download a CSV report
6. A message listener to trigger the scan

### File Structure Overview
```
content.js
├── Line 1-3:    Log + load symbols
├── Line 4-72:   Symbol list (~200 Indian stock symbols)
├── Line 73-118: categorizeStrikes() — option strike mathematics
├── Line 119-310: scanSymbol() — API call + data extraction for one symbol
├── Line 311-505: downloadCSV() — CSV generation + download trigger
├── Line 506-540: runScanner() — orchestrates scanning all symbols
└── Line 542-575: chrome.runtime.onMessage listener
```

---

### 7.3.1 — Symbol List (Lines 4–72)

```javascript
const symbols = `
NIFTY
BANKNIFTY
ABCAPITAL
...
`
    .trim()
    .split("\n")
    .map(s => s.trim())
    .filter(Boolean);
```

**What's happening:**
1. A template literal (backtick string) containing ~200 stock symbols, one per line
2. `.trim()` — removes leading/trailing whitespace
3. `.split("\n")` — splits the string into an array at each newline
4. `.map(s => s.trim())` — trims each individual symbol (removes spaces around them)
5. `.filter(Boolean)` — removes empty strings (handles extra blank lines)

**JavaScript Concept — Chaining:**
Each method call returns a value, and the next method operates on that value. Like an assembly line:
```
Raw string → trim edges → split into pieces → clean each piece → remove empties → Final array
```

**Why a template literal and not an array?**
- This format is easier to copy-paste from a list
- Adding/removing symbols is one-line edit
- An array literal would need quotes and commas for each symbol

### 7.3.2 — `categorizeStrikes()` (Lines 73–118)

### Finance Concept: What Are Option Strikes?

Before we read the code, we must understand the domain.

**Option:** A contract giving the right (not obligation) to buy/sell a stock at a specific price.

**Strike Price:** The specific price at which the option can be exercised. Example: "NIFTY 23000 CE" means "Call option at strike 23000."

**Call (CE):** Right to BUY. You profit if stock goes UP.

**Put (PE):** Right to SELL. You profit if stock goes DOWN.

**ATM (At-The-Money):** The strike closest to the current stock price.

**ITM (In-The-Money):**
- For CE: Strike BELOW current price (you could buy cheaper than market)
- For PE: Strike ABOVE current price (you could sell higher than market)

**OTM (Out-of-The-Money):**
- For CE: Strike ABOVE current price
- For PE: Strike BELOW current price

```
Example: NIFTY at 23,100

Strikes:  22900  22950  23000  23050  23100  23150  23200
           ITM4   ITM3   ITM2   ITM1    ATM   OTM1   OTM2  (for CE)
           OTM2   OTM1   ITM1*  ITM2*    ATM   ITM1   ITM2  (for PE)

* PE reverses direction — puts gain value as price drops
```

### Code Walkthrough

```javascript
function categorizeStrikes(atmStrike, strikeList) {
    strikeList = strikeList
        .map(Number)
        .sort((a, b) => a - b);
```

**`.map(Number)`** — Converts every element to a number. `Number` is a built-in function. Equivalent to `.map(s => Number(s))`. This is a functional programming pattern — passing a function as an argument.

**`.sort((a, b) => a - b)`** — Sorts numbers ascending. Critical detail: JavaScript's default `.sort()` converts everything to strings and compares lexicographically. So `[2, 10, 1].sort()` gives `[1, 10, 2]` (alphabetical order). The comparator `(a, b) => a - b` forces numeric comparison. This is one of the most common JavaScript gotchas.

```javascript
const atmIndex = strikeList.indexOf(Number(atmStrike));
```

**`indexOf`** — Finds the position of the ATM strike in the sorted array. This position is the center from which ITM and OTM buckets branch out.

```javascript
return {
    ATM: strikeList[atmIndex],

    CE: {
        ITM1: strikeList[atmIndex - 1] ?? null,  // one step below ATM
        ITM2: strikeList[atmIndex - 2] ?? null,  // two steps below
        ITM3: strikeList[atmIndex - 3] ?? null,
        ITM4: strikeList[atmIndex - 4] ?? null,
        ITM5: strikeList[atmIndex - 5] ?? null,

        OTM1: strikeList[atmIndex + 1] ?? null,  // one step above ATM
        OTM2: strikeList[atmIndex + 2] ?? null,
        OTM3: strikeList[atmIndex + 3] ?? null,
        OTM4: strikeList[atmIndex + 4] ?? null,
        OTM5: strikeList[atmIndex + 5] ?? null
    },

    PE: {
        ITM1: strikeList[atmIndex + 1] ?? null,  // ← REVERSED for PE!
        ITM2: strikeList[atmIndex + 2] ?? null,
        // ...
        OTM1: strikeList[atmIndex - 1] ?? null,  // ← REVERSED for PE!
        // ...
    }
};
```

**Nullish Coalescing (`??`):** If the left side is `null` or `undefined`, use the right side. Unlike `||`, it doesn't treat `0`, `""`, or `false` as falsy. Here: if `strikeList[atmIndex - 5]` is out of bounds (undefined), use `null`.

**The PE Reversal:**
This is the key insight. For Call options, lower strikes are ITM. For Put options, higher strikes are ITM. The function reflects this by inverting the index offsets for PE buckets.

**Interview Question:**
> Q: Why does CE_ITM1 use `atmIndex - 1` while PE_ITM1 uses `atmIndex + 1`?
>
> A: Because Call options gain value when the stock price rises above the strike, so lower strikes are "in the money" for calls. Put options gain value when the stock price falls below the strike, so higher strikes are "in the money" for puts. The function correctly models this inverse relationship.

### 7.3.3 — `scanSymbol()` (Lines 119–310)

The core data-fetching function. Makes an API call to Sensibull's backend and extracts structured OI change data.

### API Endpoint
```
POST https://oxide.sensibull.com/v1/compute/1/oi_graphs/oi_change_chart
```

This is Sensibull's internal API for Open Interest change charts. The extension talks to it directly.

### Request Payload
```javascript
{
    underlying: symbol,         // Stock symbol being queried
    mode: "intraday",           // Today's data
    expiries: {},               // All expiries (empty = all)
    atm_strike_selection: "ten",// 10 strikes around ATM
    from_time: null,            // No time range filter
    to_time: null,
    auto_update: "full_day",    // Full day of data
    show_oi: false,             // OI change, not absolute OI
    // ...
}
```

### Fetch Options
```javascript
fetch(url, {
    method: "POST",
    credentials: "include",      // Send cookies (authentication)
    headers: {
        "Content-Type": "application/json",
        "x-device-id": "83bc2e49-...",  // Static device ID
        "frt-ref": Math.random().toString(36).substring(2)  // Random ref
    },
    body: JSON.stringify(requestPayload)
});
```

**`credentials: "include"`** — Sends the user's Sensibull session cookies with the request. Without this, the API would return "Unauthorized." The user must be logged into sensibull.com in their browser.

**`x-device-id`** — A hardcoded UUID. This identifies the "device" to Sensibull's backend. Hardcoding this is questionable — every user of this extension shares the same device ID. Better approach: generate a random UUID per installation and store it in `chrome.storage`.

**`frt-ref`** — A random alphanumeric string. Likely a CSRF token or request deduplication mechanism. `Math.random().toString(36)` converts a random float to base-36 (0-9 + a-z).

### Response Processing

```javascript
const json = await response.json();

if (!json.success || !json.payload) {
    return { symbol, error: "No data returned" };
}

const responseData = json.payload;
const strikeMap = categorizeStrikes(
    responseData.atm_strike,
    responseData.strike_list
);
```

**Response Structure:**
```javascript
{
    success: true,
    payload: {
        atm_strike: 23100,           // The ATM strike price
        strike_list: [22800, 22900, 23000, ...],  // All available strikes
        current_ltp: 23145.50,       // Last Traded Price (spot)
        pcr: 1.23,                   // Put-Call Ratio
        total_call_oi_change: 50000,  // Total Call OI change
        total_put_oi_change: -30000,  // Total Put OI change
        per_strike_data: {            // Per-strike OI details
            22900: { call_oi_change: 1200, put_oi_change: -800 },
            23000: { call_oi_change: -500, put_oi_change: 2000 },
            // ...
        }
    }
}
```

### Bucket Aggregation

The function iterates through the strike map (ATM/CE_ITM1/CE_ITM2/... /PE_ITM1/...) and pulls OI change data from `per_strike_data` for each strike. Then it computes derived fields:

```javascript
// Sum of ITM Put OI changes
bucketData.ITM_PE_Total =
    (bucketData.PE_ITM1?.putOiChange || 0) +
    (bucketData.PE_ITM2?.putOiChange || 0) +
    (bucketData.PE_ITM3?.putOiChange || 0);

// Support Migration = ITM Puts - OTM Puts
bucketData.SupportMigration =
    bucketData.ITM_PE_Total - bucketData.OTM_PE_Total;

// Resistance Migration = ITM Calls - OTM Calls
bucketData.ResistanceMigration =
    bucketData.ITM_CE_Total - bucketData.OTM_CE_Total;
```

**Financial Concept — Migration:**
"Migration" refers to OI (Open Interest) shifts between ITM and OTM strikes. When traders roll positions:
- ITM PE rising + OTM PE flat/falling = Support building (traders expect floor)
- ITM CE rising + OTM CE flat/falling = Resistance building (traders expect ceiling)

A positive SupportMigration means more put OI is building at ITM strikes — a bullish signal. A positive ResistanceMigration means more call OI at ITM strikes — a bearish signal.

**Return Shape:**
```javascript
{
    symbol: "NIFTY",
    spot: 23145.50,
    pcr: 1.23,
    totalCallOI: 50000,
    totalPutOI: -30000,
    ATM: { strike: 23100, callOiChange: -500, putOiChange: 2000 },
    CE_ITM1: { strike: 23000, callOiChange: 1200 },
    CE_ITM2: { strike: 22900, callOiChange: 800 },
    // ... all buckets
    ITM_PE_Total: 4500,
    OTM_PE_Total: 2000,
    ITM_CE_Total: 3000,
    OTM_CE_Total: 5000,
    SupportMigration: 2500,     // 4500 - 2000
    ResistanceMigration: -2000  // 3000 - 5000
}
```

### 7.3.4 — `downloadCSV()` (Lines 311–505)

### Purpose
Takes scan results and generates a CSV file, then triggers a browser download.

### How CSV Generation Works

```javascript
const headers = ["Symbol", "Spot", "PCR", "ATM_Strike", ...];

const csvRows = rows.map(r => [
    r.symbol,
    r.spot,
    r.pcr,
    r.ATM?.strike,
    r.ATM?.callOiChange,
    // ... 50+ fields
].join(","));

const csv = [headers.join(","), ...csvRows].join("\n");
```

**What a CSV looks like:**
```
Symbol,Spot,PCR,ATM_Strike,ATM_CallOI,...
NIFTY,23145.50,1.23,23100,-500,2000,1200,...
BANKNIFTY,49100.00,1.45,49000,300,-200,...
```

Lines separated by `\n`, fields separated by `,`.

### How Download Works

```javascript
const blob = new Blob([csv], { type: "text/csv" });
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = `sensibull_oi_scan_${ts}.csv`;
a.click();
URL.revokeObjectURL(url);
```

**`Blob` (Binary Large Object):** A file-like object in memory. We create one containing our CSV text.

**`URL.createObjectURL(blob)`** — Creates a temporary URL (like `blob:chrome-extension://abc123/...`) that points to our in-memory file. This URL only works in THIS browser session.

**Programmatic Click:**
1. Create a hidden `<a>` element
2. Set its `href` to the blob URL
3. Set `download` attribute with desired filename
4. Call `.click()` to trigger the browser's download dialog
5. Clean up the blob URL with `revokeObjectURL()`

**Why not use `chrome.downloads` API?**
The `chrome.downloads` API requires the `"downloads"` permission (which the manifest has, but the code doesn't use). This blob-click approach works in content scripts without calling `chrome.downloads.download()`. Both are valid. The blob approach has the advantage of not requiring an additional API call, but it can't set the download folder or handle large files well.

### Timestamp Formatting
```javascript
const now = new Date();
const ts = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}-${String(now.getMinutes()).padStart(2, "0")}-${String(now.getSeconds()).padStart(2, "0")}`;
```

**`now.getMonth() + 1`** — JavaScript months are 0-indexed (January = 0, December = 11). Adding 1 converts to human-readable months.

**`.padStart(2, "0")`** — Ensures single-digit numbers get a leading zero: `5` → `"05"`, `12` → `"12"`. Without this, timestamps would be inconsistent lengths.

**Result:** `sensibull_oi_scan_2026-06-15_14-30-45.csv`

### 7.3.5 — `runScanner()` (Lines 506–540)

### Purpose
The orchestrator. Loops through all 200 symbols, calls `scanSymbol()` for each, collects results, triggers download.

```javascript
async function runScanner() {
    const results = [];

    for (let i = 0; i < symbols.length; i++) {
        const symbol = symbols[i];
        console.log(`Scanning ${i + 1}/${symbols.length}: ${symbol}`);

        const result = await scanSymbol(symbol);
        results.push(result);

        await new Promise(resolve => setTimeout(resolve, 1000));
    }

    downloadCSV(results);
    return results.length;
}
```

### Sequential Processing
The function processes symbols ONE AT A TIME. `await scanSymbol(symbol)` blocks until the API call completes. This is intentional — it includes rate limiting.

### Rate Limiting (The `setTimeout` Trick)
```javascript
await new Promise(resolve => setTimeout(resolve, 1000));
```

**What this does:**
1. `setTimeout(resolve, 1000)` — schedules `resolve()` to run after 1000ms
2. `new Promise(...)` — creates a Promise that completes when `resolve()` is called
3. `await` — pauses the function until the Promise resolves
4. Net effect: waits exactly 1 second between API calls

**Why rate limit?** Sending 200 API requests simultaneously would:
- Overwhelm Sensibull's servers (looks like a DDoS attack)
- Risk getting IP-banned
- Fill up the browser's concurrent connection pool (Chrome allows ~6 concurrent requests per domain)

**Why 1 second?** It's a heuristic. For a production system, you'd check response headers for rate limit info (`X-RateLimit-Remaining`, `Retry-After`) and adjust dynamically.

### JavaScript Concept — Manual Promise Creation
This is a pattern worth understanding:

```javascript
// The "sleep" pattern:
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Usage:
await sleep(1000);  // Waits 1 second
```

You wrap `setTimeout` in a Promise because `setTimeout` is callback-based but `await` expects Promises. This bridges the old callback world with the modern async/await world.

### 7.3.6 — Message Listener (Lines 542–575)

```javascript
chrome.runtime.onMessage.addListener(
    (request, sender, sendResponse) => {
        if (request.action === "runScan") {
            runScanner()
                .then(count => {
                    sendResponse({ message: `Completed ${count} symbols` });
                })
                .catch(error => {
                    sendResponse({ message: error.message });
                });
            return true;  // ← CRITICAL: tells Chrome to wait for async response
        }
    }
);
```

**The Message Contract:**
- **Sender (popup.js):** `chrome.tabs.sendMessage(tab.id, { action: "runScan" })`
- **Receiver (content.js):** `chrome.runtime.onMessage.addListener(...)`
- **Response:** Content script calls `sendResponse(...)`, popup receives it as the return value of `sendMessage()`

**`return true`:** Tells Chrome "I'll call sendResponse asynchronously." Without it, Chrome closes the message channel immediately after the listener returns, and `sendResponse()` would do nothing. This is the #1 source of messaging bugs in Chrome Extensions.

**`sender` parameter:** Contains info about who sent the message:
```javascript
{
    id: "extension-id-abc123",
    origin: "chrome-extension://extension-id-abc123",
    tab: { id: 42, url: "https://web.sensibull.com/..." }
}
```
The code doesn't validate `sender` — it accepts messages from any source. This is a security concern. In production, you should verify `sender.id === chrome.runtime.id` to ensure the message came from your own extension.

---

## 8. CHROME APIs USED IN THIS EXTENSION

### 8.1 — `chrome.tabs.query()`
```javascript
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
```
- **API Family:** Tabs API
- **Permission Needed:** `activeTab`
- **Returns:** Array of `Tab` objects matching the criteria
- **Use in this project:** Finding the active tab to send a message to

### 8.2 — `chrome.tabs.sendMessage()`
```javascript
const response = await chrome.tabs.sendMessage(tab.id, { action: "runScan" });
```
- **Sends a message from extension pages (popup, background) to content scripts**
- **First argument:** Target tab ID
- **Second argument:** Any JSON-serializable object
- **Returns:** The response from `sendResponse()` in the content script
- **Note:** This is extension → content script only. For extension → extension, use `chrome.runtime.sendMessage()`

### 8.3 — `chrome.runtime.onMessage.addListener()`
```javascript
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => { ... });
```
- **Listens for messages from ANY extension context**
- Used by content scripts to receive messages from the popup
- `request` — the message object
- `sender` — info about who sent it
- `sendResponse` — function to call to reply (only usable once)

---

## 9. JAVASCRIPT CONCEPTS DEEP DIVE

### 9.1 — Async/Await

**Concept:** A way to write asynchronous code that looks synchronous. Under the hood, it's Promises.

**Real-world analogy:** Ordering at a restaurant. You place your order (start async operation), the kitchen works on it, and you wait. When food arrives, you eat (the `await` resolves). You don't stand frozen at the counter — you can do other things while waiting.

**The Event Loop:**
```
Call Stack → Web APIs → Task Queue → Call Stack
                                ↑
                            (Event Loop moves tasks
                             when Call Stack is empty)
```

When you `await`, the function pauses but the event loop keeps running. Other code (event listeners, other functions) can still execute. Once the awaited Promise resolves, the function resumes.

**In this project:**
```javascript
const result = await scanSymbol(symbol);  // Pauses here
results.push(result);                       // Resumes here after API response
```

### 9.2 — Arrow Functions

Three forms used in this project:

```javascript
// 1. Expression body (implicit return)
symbols.map(s => s.trim())

// 2. Block body (explicit return)
symbols.map((s) => { return s.trim(); })

// 3. Async arrow
async () => { await something(); }
```

**Key difference from regular functions:**
- Arrow functions don't have their own `this` — they inherit from the enclosing scope
- Cannot be used as constructors (`new`)
- Shorter syntax

### 9.3 — Object Literals and Spread

```javascript
return {
    symbol,
    spot: responseData.current_ltp,
    ...bucketData  // Spread: copies all bucketData keys into this object
};
```

**Spread operator (`...`):** Takes all properties from one object and spreads them into another. Equivalent to:
```javascript
Object.assign({}, { symbol, spot: ... }, bucketData)
```

### 9.4 — Short-circuit Evaluation

```javascript
status.innerText = response?.message || "No Response";
```

This is short-circuit evaluation. If `response?.message` is truthy, use it. Otherwise, short-circuit to `"No Response"`. Common pattern for providing defaults.

### 9.5 — Computed Property Names

```javascript
bucketData[`CE_${bucket}`] = { ... };
```

The bracket notation with a template literal creates dynamic property names: `CE_ITM1`, `CE_ITM2`, `CE_OTM1`, etc. Without this, you'd need repetitive code for each bucket.

---

## 10. BROWSER CONCEPTS

### 10.1 — Same-Origin Policy (SOP)

The most important security concept in web browsers.

**Rule:** A script from origin A can only read data from origin A. Origin = protocol + host + port.

```
https://web.sensibull.com:443  ← One origin
https://oxide.sensibull.com:443 ← Different origin (different host)
```

**Why this matters for this extension:** The content script runs on `web.sensibull.com` but fetches data from `oxide.sensibull.com`. Without `host_permissions` granting access to `oxide.sensibull.com`, the browser would block this `fetch()` call.

### 10.2 — CORS (Cross-Origin Resource Sharing)

CORS is how servers say "it's okay for other origins to access me."

Sensibull's API server at `oxide.sensibull.com` must include headers like:
```
Access-Control-Allow-Origin: https://web.sensibull.com
Access-Control-Allow-Credentials: true
```

Since this extension uses `credentials: "include"` (sends cookies), the server must also allow credentials in CORS.

### 10.3 — Extension Origins

Extensions have their own origin: `chrome-extension://<32-char-id>/`. Content scripts "run at" the web page's origin, but with elevated privileges from host_permissions.

---

## 11. SECURITY REVIEW

### 11.1 — Unused Permission
**Issue:** `"downloads"` permission is declared but never used. The code creates blob downloads instead.
**Risk:** Low, but violates the principle of least privilege. During Chrome Web Store review, extra permissions trigger more scrutiny.
**Fix:** Remove `"downloads"` from `permissions` array.

### 11.2 — Missing Sender Validation
```javascript
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    // No check on sender!
    if (request.action === "runScan") { ... }
});
```

**Risk:** Any website can send messages to this content script. A malicious page on `web.sensibull.com` could trigger the scanner.
**Impact:** The scanner would run, making 200 API calls and downloading a CSV. No data leak (the extension doesn't send data to external servers), but could cause unwanted downloads or rate limit exhaustion.
**Fix:**
```javascript
if (sender.id !== chrome.runtime.id) return; // Only accept messages from our extension
```

### 11.3 — Hardcoded Device ID
```javascript
"x-device-id": "83bc2e49-de14-45bc-91cb-ede7c156b16f"
```

**Risk:** All users share the same device fingerprint. Sensibull could:
- Rate limit the entire extension (all users affected)
- Block the device ID, breaking the extension for everyone
- Track users collectively (privacy concern)

**Fix:** Generate a random UUID on installation and persist in `chrome.storage.local`.

### 11.4 — No Authentication Validation
**Risk:** The extension assumes the user is logged into Sensibull. No check is performed before making requests. If the session expires, all 200 API calls will fail — silently producing a CSV full of errors.
**Fix:** Check authentication status before starting the scan.

### 11.5 — Data Exposure via Console Logging
```javascript
console.log(symbol, responseData);
```

**Risk:** The entire API response (including potentially sensitive options data) is logged to the browser console. Anyone with physical access to the machine can open DevTools and see historical scan data.
**Impact:** Low for this use case (options data is semi-public), but bad practice for production code.
**Fix:** Remove or guard production logging.

### 11.6 — No Input Validation on Messages
```javascript
if (request.action === "runScan") { ... }
```

**Risk:** No validation of the message shape. If a message arrives with `action: "runScan"` but missing expected fields, the code still executes.
**Impact:** Low (the action string is the only field), but defensive programming is important.

### Security Summary Table
| Finding | Severity | Impact |
|---------|----------|--------|
| Unused `downloads` permission | Low | Extra WRS scrutiny |
| Missing sender validation | Medium | Unauthorized scan trigger |
| Hardcoded device ID | Medium | All users share fingerprint |
| No auth check | Low | Silent failures |
| Console logging raw data | Low | Data visible in DevTools |

---

## 12. PERFORMANCE REVIEW

### 12.1 — Sequential vs Parallel Processing
Currently: 200 symbols × (API time + 1s delay) = ~3-4 minutes minimum.

**Option A: Batching (5 concurrent)**
```javascript
async function runBatch(symbols, batchSize = 5) {
    for (let i = 0; i < symbols.length; i += batchSize) {
        const batch = symbols.slice(i, i + batchSize);
        const results = await Promise.all(batch.map(scanSymbol));
        results.forEach(r => allResults.push(r));
        await sleep(1000); // Rate limit between batches
    }
}
```
This would cut total time by ~5x while still respecting rate limits.

**Option B: Worker-based (if Sensibull allows)**
Offload scanning to a service worker, allowing the popup to close while the scan continues. This would require restructuring the architecture to include a background service worker.

### 12.2 — Memory: Building Large CSV in Memory
The entire dataset (200 symbols × ~50 fields) is built as an array of objects, then converted to CSV, then to a Blob — all in memory. For 200 symbols this is fine (~100KB raw). For 10,000 symbols, this would be a problem.

### 12.3 — No Progress Reporting
The popup shows "Starting..." for the entire scan duration. Users have no idea if it's working, stuck, or almost done. A long-lived connection (chrome.runtime.connect / Port) would allow streaming progress updates.

### 12.4 — CSS/HTML Performance (Negligible)
The popup is 300px with inline CSS. No performance concerns at this scale.

### 12.5 — Content Script Injection Performance
Content script injects on EVERY page load on `web.sensibull.com`, even if the user never uses the extension. The script is 675 lines — modest, but it executes `console.log` and loads 200 symbol strings into memory on every page visit. This is wasted work if the user never clicks "Run Scan."

**Fix:** Defer heavy initialization to when the scan actually runs.

---

## 13. SOFTWARE ENGINEERING PATTERNS

### 13.1 — Message-Based Communication
**Pattern:** The extension uses messaging as its sole communication mechanism. This is Chrome's recommended architecture — each component is isolated, communicating only through well-defined message interfaces.

**Why:** Loose coupling. The popup doesn't know how the content script works internally. It just knows: "send `{action:'runScan'}` and you'll get back `{message:'...'}`."

### 13.2 — Data Transformation Pipeline
```
Raw API JSON → categorizeStrikes() → bucketData → scanSymbol return → runScanner results[] → downloadCSV → CSV Blob
```

Each stage transforms data into a new shape. This is functional-style data processing — pure functions (except the fetch side effect) that take input and produce output without mutating shared state.

### 13.3 — Async Iterator (Manual)
```javascript
for (let i = 0; i < symbols.length; i++) {
    const result = await scanSymbol(symbols[i]);
    results.push(result);
}
```

This is essentially a manual async iterator — processing items one at a time with delays between them. A modern alternative would be `for...of` with async generators, but the traditional `for` loop is clearer for this use case.

---

## 14. REFACTORING OPPORTUNITIES (Ranked by Impact)

### High Impact

**1. Add Background Service Worker + Progress Updates**
Move `runScanner()` to a background service worker. Use `chrome.runtime.connect()` for progress messages. This lets the popup close without stopping the scan and shows real-time progress.

**2. Batch API Calls**
Process 5 symbols concurrently instead of sequentially. ~5x speed improvement.

**3. Fix Security Issues**
- Add sender validation in message listener
- Remove unused `downloads` permission
- Generate per-installation device ID
- Remove console.log of raw API data

### Medium Impact

**4. Defer Content Script Initialization**
Don't parse the symbol list until the scan is actually triggered. Saves memory on every page load.

**5. Add Error Recovery**
If an API call fails (network error, rate limit), retry with exponential backoff instead of just logging and continuing.

**6. Use `chrome.storage` for Symbol List**
Move the 200-symbol list to `chrome.storage.local` or a separate JSON file. This makes updates possible without redeploying the extension.

### Low Impact

**7. TypeScript Migration**
Add type safety. This is a JavaScript project that would benefit greatly from TypeScript — especially for the complex nested data structures in the API response.

**8. Add Tests**
Unit tests for `categorizeStrikes()`, integration tests for the API response parsing, E2E tests for the full scan flow.

**9. Extracting Constants**
Magic values like `"83bc2e49-..."`, `"https://oxide.sensibull.com/..."`, and the rate limit delay (1000ms) should be named constants.

---

## 15. TECHNICAL DEBT ANALYSIS

| Severity | Item | Explanation |
|----------|------|-------------|
| **Critical** | None | The extension works for its intended purpose |
| **High** | Missing sender validation | Security vulnerability |
| **High** | Sequential processing | Poor user experience for 200+ symbols |
| **Medium** | Hardcoded device ID | Maintenance and privacy concern |
| **Medium** | No TypeScript | Fragile with complex nested data |
| **Medium** | Symbol list in source code | Can't update without redeploy |
| **Low** | Console pollution | Debugging logs in production |
| **Low** | Unused permission | Chrome Web Store review friction |
| **Low** | No tests | Risky to refactor |

---

## 16. ARCHITECTURE DIAGRAMS

### 16.1 — Full Extension Architecture
```
┌────────────────────────────────────────────────────┐
│              CHROME BROWSER                         │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │            EXTENSION PACKAGE                  │  │
│  │  chrome-extension://abc123/                   │  │
│  │                                               │  │
│  │  ┌───────────┐    ┌──────────────────────┐   │  │
│  │  │ popup.html│    │    content.js         │   │  │
│  │  │ popup.js  │    │    (injected into     │   │  │
│  │  │           │    │     web.sensibull.com) │   │  │
│  │  │  300px    │    │                       │   │  │
│  │  │  card     │    │  ┌─────────────────┐  │   │  │
│  │  │           │    │  │ runScanner()    │  │   │  │
│  │  └─────┬─────┘    │  │  ↓              │  │   │  │
│  │        │          │  │ scanSymbol()    │  │   │  │
│  │        │  send    │  │  ↓              │  │   │  │
│  │        │ Message  │  │ categorizeStr() │  │   │  │
│  │        │          │  │  ↓              │  │   │  │
│  │        └──────────┼──┤ downloadCSV()   │  │   │  │
│  │                   │  └─────────────────┘  │   │  │
│  │                   └──────────────────────┘   │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │         EXTERNAL API                           │  │
│  │    oxide.sensibull.com/v1/compute/...          │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### 16.2 — Request Flow Diagram
```
[User]                        [Chrome]                     [Sensibull]
  │                              │                             │
  │ ① Navigate to                │                             │
  │   web.sensibull.com          │                             │
  │─────────────────────────────►│                             │
  │                              │                             │
  │                              │ ② Inject content.js         │
  │                              │   into page                 │
  │                              │                             │
  │ ③ Click extension icon      │                             │
  │─────────────────────────────►│                             │
  │                              │                             │
  │                              │ ④ Load popup.html           │
  │                              │                             │
  │ ⑤ Click "Run Scan"          │                             │
  │─────────────────────────────►│                             │
  │                              │                             │
  │                              │ ⑥ popup.js sends message    │
  │                              │   {action:"runScan"}        │
  │                              │   to content.js             │
  │                              │                             │
  │                              │ ⑦ runScanner() starts       │
  │                              │                             │
  │                              │ ⑧ For each of 200 symbols: │
  │                              │   POST /oi_change_chart ───►│
  │                              │   ◄─── JSON response        │
  │                              │   wait 1 second             │
  │                              │                             │
  │                              │ ⑨ downloadCSV()             │
  │                              │   creates Blob              │
  │                              │   triggers download         │
  │                              │                             │
  │ ⑩ CSV downloads to PC      │                             │
  │◄─────────────────────────────│                             │
```

### 16.3 — Data Flow Diagram
```
[Symbol List]  ────────────────────────────────────────────┐
  "NIFTY\nBANKNIFTY\n..."                                   │
    │                                                       │
    ▼                                                       │
[categorizeStrikes()]  ◄──── API Response                   │
  strikeList → {ATM, CE:{ITM1..5,OTM1..5}, PE:{...}}       │
    │                                                       │
    ▼                                                       │
[scanSymbol()]  ──fetch()──►  oxide.sensibull.com          │
    │                         /v1/compute/1/oi_graphs/...   │
    │                              │                        │
    │                         ◄──── JSON                    │
    │                                                       │
    ▼                                                       │
{                                                           │
  symbol, spot, pcr,                                        │
  ATM: {strike, callOiChange, putOiChange},                 │
  CE_ITM1: {...}, CE_ITM2: {...}, ...                       │
  PE_ITM1: {...}, ...                                       │
  ITM_PE_Total, OTM_PE_Total,                               │
  SupportMigration, ResistanceMigration                     │
}                                                           │
    │                                                       │
    ▼                                                       │
[runScanner()]  ──collects──►  results[] (200 objects)     │
    │                                                       │
    ▼                                                       │
[downloadCSV()]                                             │
    │                                                       │
    ▼                                                       │
Symbol,Spot,PCR,ATM_Strike,...\n                            │
NIFTY,23145.5,1.23,...\n                                    │
...                                                         │
    │                                                       │
    ▼                                                       │
[Blob] → [Object URL] → [<a> click] → [Downloads folder]   │
```

### 16.4 — Extension Lifecycle
```
┌──────────────────────────────────────────────────┐
│               INSTALLATION                         │
│                                                    │
│  User installs from Chrome Web Store / .zip        │
│       │                                            │
│       ▼                                            │
│  Chrome reads manifest.json                        │
│       │                                            │
│       ▼                                            │
│  Chrome registers content script                   │
│  injection rules: web.sensibull.com/*              │
│                                                    │
├──────────────────────────────────────────────────┤
│               DAILY USE                            │
│                                                    │
│  User opens web.sensibull.com                      │
│       │                                            │
│       ▼                                            │
│  Chrome injects content.js into page               │
│  content.js registers message listener             │
│  (waits silently, no visible effect)               │
│       │                                            │
│       ▼                                            │
│  User clicks extension icon                        │
│       │                                            │
│       ▼                                            │
│  popup.html loads, popup.js executes               │
│  (this takes ~50ms)                                │
│       │                                            │
│       ▼                                            │
│  User clicks "Run Scan"                            │
│       │                                            │
│       ▼                                            │
│  Message sent: {action:"runScan"}                  │
│       │                                            │
│       ▼                                            │
│  content.js runs scanner                           │
│  (3-4 minutes, 200 API calls)                      │
│       │                                            │
│       ▼                                            │
│  CSV downloads                                     │
│       │                                            │
│       ▼                                            │
│  Popup shows "Completed 200 symbols"               │
│                                                    │
├──────────────────────────────────────────────────┤
│               SHUTDOWN                             │
│                                                    │
│  User closes popup → popup.js destroyed            │
│  User closes tab → content.js destroyed            │
│  User uninstalls extension → all files removed     │
│                                                    │
│  Note: No persistent state. Nothing survives       │
│  between sessions.                                  │
└──────────────────────────────────────────────────┘
```

---

## 17. TESTING STRATEGY

### What to Test

**Unit Tests:**
- `categorizeStrikes()` — test edge cases: empty strike list, ATM at boundary, null atmStrike
- CSV header generation — verify all expected columns are present
- Symbol list parsing — verify no empty strings, all symbols trimmed

**Integration Tests:**
- Mock the Sensibull API, verify `scanSymbol()` correctly transforms response to output
- Test the full `runScanner()` flow with 3 mock symbols

**E2E Tests:**
- Load extension in Puppeteer/Playwright
- Navigate to a mock Sensibull page
- Click extension, verify popup appears
- Click "Run Scan," verify CSV downloads

---

## 18. INTERN → JUNIOR DEVELOPER ROADMAP

Based on what this project teaches, here's what to learn next:

### Phase 1: JavaScript Fundamentals (master these first)
1. **Promises and Async/Await** — This project is async-heavy. Understand the event loop, microtasks vs macrotasks.
2. **Array Methods** — `map`, `filter`, `reduce`, `forEach`, `sort` — used pervasively here.
3. **Object Destructuring and Spread** — Used in scanSymbol return values.

### Phase 2: Browser Knowledge
4. **The DOM** — How browsers parse HTML, build the DOM tree, and how JavaScript interacts with it.
5. **Fetch API** — Learn HTTP methods, headers, CORS, cookies, and how `fetch()` works at the network level.
6. **Same-Origin Policy** — The foundation of web security. Understand why it exists and how extensions bypass it.

### Phase 3: Chrome Extension Specifics
7. **MV3 Architecture** — Service workers, declarativeNetRequest, and the differences from MV2.
8. **Message Passing** — One-time messages vs ports/long-lived connections.
9. **chrome.storage API** — Local, sync, and session storage for extensions.
10. **Content Script Isolation** — Understand "isolated world" and when to use `MAIN` world injection.

### Phase 4: Software Engineering
11. **TypeScript** — This project would benefit enormously from type safety.
12. **Error Handling Patterns** — Retry logic, exponential backoff, circuit breakers.
13. **Testing** — Jest for unit tests, Playwright for E2E tests.
14. **State Management** — As extensions grow, managing state across popup/background/content becomes complex.

### Phase 5: Extension Publishing
15. **Chrome Web Store Process** — Review requirements, privacy policies, manifest permissions.
16. **Extension Updates** — How to version and deploy updates.
17. **Analytics** — Track usage without violating user privacy.

---

## 19. COMMON MISTAKES IN THIS PROJECT (Learning Opportunities)

1. **Forgetting `return true` in onMessage listener** — Already done correctly here, but this is the #1 bug extension devs face.

2. **Assuming popup survives** — The popup dies instantly when clicked away. Any async operation started in the popup must either: complete before the popup closes, or be handled by a service worker.

3. **Not validating message senders** — The content script accepts messages from anyone. Always check `sender.id`.

4. **Hardcoding credentials** — The device ID is hardcoded. Never hardcode secrets, tokens, or identifiers.

5. **Console.log in production** — Logging API responses leaks data. Use environment-based logging or remove before publishing.

6. **Sequential processing without progress** — The user sees "Starting..." for 4 minutes. Always show progress or allow cancellation.

7. **Unused permissions** — `"downloads"` is declared but blob-based download is used instead. Clean up unused permissions.

---

## 20. INTERVIEW QUESTIONS (Test Yourself)

1. **Why can't the popup directly call `fetch()` to Sensibull's API instead of sending a message to the content script?**
   *Answer:* The popup runs at `chrome-extension://` origin. Sensibull's API expects cookies from `web.sensibull.com`. The content script runs in the web page's context, so it can send those cookies via `credentials: "include"`. Also, `oxide.sensibull.com` is in `host_permissions`, granting the extension cross-origin access from the content script context.

2. **What would happen if we removed `"activeTab"` from permissions?**
   *Answer:* `chrome.tabs.query()` would return an empty array because the extension no longer has permission to read tab information. `chrome.tabs.sendMessage()` would fail because the extension can't identify or target the tab.

3. **What's the difference between `chrome.runtime.sendMessage()` and `chrome.tabs.sendMessage()`?**
   *Answer:* `chrome.runtime.sendMessage()` sends to any extension context (background, popup, options). `chrome.tabs.sendMessage()` specifically targets content scripts in a particular tab.

4. **Why does the PE bucket map have reversed ITM/OTM compared to CE?**
   *Answer:* Call options are ITM when the strike is below the spot price (you can buy below market). Put options are ITM when the strike is above the spot price (you can sell above market). The buckets correctly reflect this inverse relationship.

5. **What security risk does the hardcoded `x-device-id` pose?**
   *Answer:* All users share the same device fingerprint. Sensibull could rate-limit or block the entire extension. It also enables tracking all extension users collectively. A proper implementation would generate a unique UUID per installation and store it in `chrome.storage`.

---

## 21. LEARNING SUMMARY

### Chrome Extension Concepts Learned
- MV3 manifest structure
- Popup lifecycle (born on click, dies on blur)
- Content script injection and isolated worlds
- Message passing (sendMessage / onMessage)
- `return true` pattern for async responses
- Permission model (activeTab, host_permissions)
- Content script capabilities and limitations

### JavaScript Concepts Learned
- Async/await and the event loop
- Array chaining (trim → split → map → filter)
- Nullish coalescing (`??`) vs logical OR (`||`)
- Optional chaining (`?.`)
- Arrow functions and implicit returns
- Object spread and computed property names
- Blob API and URL.createObjectURL
- Manual Promise creation (sleep pattern)
- Template literals
- Destructuring assignment

### Browser Concepts Learned
- Same-Origin Policy
- CORS and credentials
- Extension origins (`chrome-extension://`)
- Browser download triggering (blob URL + click)

### Architecture Concepts Learned
- Message-based communication pattern
- Data transformation pipelines
- Rate limiting strategies
- Content script architecture
- Extension security model

---

*This document is a complete learning guide for the Sensibull OI Scanner Chrome Extension. Work through it section by section, and test yourself with the interview questions at the end.*
