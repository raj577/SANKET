// ========== TAB NAVIGATION ==========
document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById(`panel-${tab.dataset.tab}`).classList.add("active");

        // Load data when switching tabs
        if (tab.dataset.tab === "watchlist") loadWatchlistUI();
        if (tab.dataset.tab === "history") loadHistory();
        if (tab.dataset.tab === "settings") loadSettings();
    });
});

// ========== ALL SYMBOLS ==========
const ALL_SYMBOLS = [
    "NIFTY","BANKNIFTY","ABCAPITAL","ADANIENSOL","GODFRYPHLP","INDHOTEL","INDIANB",
    "INOXWIND","JINDALSTEL","MPHASIS","NESTLEIND","NTPC","PRESTIGE","RBLBANK",
    "SHREECEM","TATAELXSI","TATASTEEL","TCS","ADANIPOWER","AMBUJACEM","APLAPOLLO",
    "AUROPHARMA","BAJAJHLDNG","BSE","CDSL","CONCOR","DALBHARAT","EICHERMOT","INDIGO",
    "JIOFIN","KAYNES","KEI","MFSL","NYKAA","PAGEIND","PERSISTENT","PNBHOUSING",
    "SBILIFE","TIINDIA","TITAN","TRENT","UNIONBANK","YESBANK","ABB","BDL","BEL",
    "BHEL","CGPOWER","GMRAIRPORT","HAL","HCLTECH","JUBLFOOD","OBEROIRLTY","ONGC",
    "PNB","POWERGRID","SONACOMS","AXISBANK","COCHINSHIP","ETERNAL","GVT&D",
    "HINDPETRO","IDFCFIRSTB","LODHA","TVSMOTOR","BAJAJ-AUTO","BOSCHLTD","CIPLA",
    "DLF","DRREDDY","EXIDEIND","GODREJPROP","KOTAKBANK","M&M","NATIONALUM","NHPC",
    "PAYTM","PGEL","TECHM","ULTRACEMCO","BANKINDIA","BIOCON","COALINDIA","COLPAL",
    "FEDERALBNK","FORCEMOT","GODREJCP","KPITTECH","LT","NMDC","OIL","PHOENIXLTD",
    "PIIND","TATACONSUM","WIPRO","BHARATFORG","CROMPTON","INDUSTOWER","NAM-INDIA",
    "PATANJALI","POWERINDIA","SOLARINDS","TATAPOWER","VOLTAS","APOLLOHOSP","DELHIVERY",
    "DIXON","FORTIS","GLENMARK","HINDUNILVR","ICICIPRULI","IDEA","NBCC","POLYCAB",
    "ALKEM","ASHOKLEY","ASTRAL","BANKBARODA","BHARTIARTL","BPCL","CHOLAFIN",
    "CUMMINSIND","DIVISLAB","IEX","INDUSINDBK","JSWENERGY","KALYANKJIL","LAURUSLABS",
    "LTF","MANAPPURAM","MARICO","MOTHERSON","MOTILALOFS","RELIANCE","SRF","SWIGGY",
    "VMM","ZYDUSLIFE","ADANIGREEN","ADANIPORTS","BAJAJFINSV","BLUESTARCO","DABUR",
    "HDFCAMC","IOC","ITC","MAXHEALTH","OFSS","PIDILITIND","SBIN","360ONE","ADANIENT",
    "JSWSTEEL","LICI","POLICYBZR","PREMIERENE","SAIL","SUZLON","UPL","VEDL",
    "ASIANPAINT","BRITANNIA","GRASIM","HDFCLIFE","ICICIBANK","ICICIGI","INFY",
    "KFINTECH","MARUTI","MUTHOOTFIN","PFC","SAMMAANCAP","SUNPHARMA","SUPREMEIND",
    "UNOMINDA","COFORGE","GAIL","HAVELLS","HDFCBANK","HEROMOTOCO","MANKIND","MAZDOCK",
    "MCX","NUVAMA","PETRONET","SIEMENS","UNITDSPR","AMBER","BAJFINANCE","CANBK",
    "DMART","HINDZINC","IREDA","LICHSGFIN","LTM","LUPIN","RADICO","RVNL","SHRIRAMFIN",
    "TMPV","ANGELONE","AUBANK","BANDHANBNK","CAMS","HINDALCO","HYUNDAI","IRFC",
    "NAUKRI","RECLTD","SBICARD","TORNTPHARM","WAAREEENER","VBL"
];

let selectedSymbols = new Set();
let lastScanResults = null;
let currentWatchlistName = "Default";

// ========== SCAN PANEL ==========

document.getElementById("scanTodayBtn").addEventListener("click", () => startScan(false, true));
document.getElementById("scanBtn").addEventListener("click", () => startScan(false));
document.getElementById("scanWatchlistBtn").addEventListener("click", () => startScan(true));

async function startScan(watchlistOnly, todayOnly = false) {
    const status = document.getElementById("status");
    const scanBtn = document.getElementById("scanBtn");
    const scanWlBtn = document.getElementById("scanWatchlistBtn");
    const scanTodayBtn = document.getElementById("scanTodayBtn");

    scanBtn.disabled = true;
    scanWlBtn.disabled = true;
    scanTodayBtn.disabled = true;

    // Today-only ignores date fields and forces intraday for the current day
    const fromDate = todayOnly ? null : (document.getElementById("fromDate").value || null);
    const toDate = todayOnly ? null : (document.getElementById("toDate").value || null);
    const mode = todayOnly ? "intraday" : document.getElementById("mode").value;
    const expiry = document.getElementById("expiry").value || null;

    // Scan tuning options
    const delayMs = parseInt(document.getElementById("delayMs").value) || 1000;
    const depth = parseInt(document.getElementById("depth").value) || 5;
    const maxRetries = parseInt(document.getElementById("maxRetries").value) || 0;

    let symbolsToScan = ALL_SYMBOLS;
    if (watchlistOnly) {
        const activeName = document.getElementById("activeWatchlistSelect").value;
        const data = await chrome.storage.local.get("watchlists");
        const lists = data.watchlists || {};
        const wl = lists[activeName] || [];
        symbolsToScan = wl.length > 0 ? wl : ALL_SYMBOLS;
    }

    // Surface the real upload state at scan time, not just in Settings.
    let uploadStateLine = "";
    try {
        const { backendConfig } = await chrome.storage.local.get("backendConfig");
        const uploadOn = backendConfig?.uploadEnabled === true;
        uploadStateLine = uploadOn
            ? `<div style="margin-top:4px;font-size:11px;color:#4caf50">Backend upload: ON (archives to database)</div>`
            : `<div style="margin-top:4px;font-size:11px;color:#ef5350">Backend upload: OFF — scans save only to Downloads. Enable in Settings.</div>`;
    } catch (error) {
        // Storage is always available in a popup; ignore defensively.
    }

    status.innerHTML = `<div>Starting scan of ${symbolsToScan.length} symbols...</div>${uploadStateLine}<div class="progress-bar"><div class="fill" id="progressFill"></div></div>`;

    // Progress messages are broadcast by the content script and received here.
    const progressListener = (message) => {
        if (message.action === "scanProgress") {
            const pct = Math.round((message.current / message.total) * 100);
            const fill = document.getElementById("progressFill");
            if (fill) fill.style.width = pct + "%";
            status.innerHTML = `<div>[${message.date || "today"}] ${message.current}/${message.total}: ${message.symbol}</div><div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div>`;
        }
        if (message.action === "scanComplete") {
            lastScanResults = message.results;
            renderDashboard(message.results);
            chrome.runtime.sendMessage({
                action: "saveScanHistory",
                scanData: {
                    count: message.results.length,
                    mode, fromDate, toDate, expiry, depth,
                    results: message.results
                }
            });
            sendTelegramSummary(message.results);
        }
    };

    chrome.runtime.onMessage.addListener(progressListener);

    try {
        const response = await chrome.runtime.sendMessage({
            action: "orchestrateScan",
            options: {
                fromDate, toDate, mode, expiry,
                symbols: symbolsToScan,
                delayMs, depth, maxRetries,
                reportProgress: true,
                trigger: "manual"
            }
        });

        if (!response || response.ok === false) {
            throw new Error(response?.error || "Scan failed");
        }

        let message;
        if (response.upload) {
            const prefix = response.status === "FAILED"
                ? `⚠️ CSV archived as ${response.csvFilename}, but scanning failed`
                : `✅ Archived ${response.csvFilename} — ${response.status}`;
            message = `${prefix} · ${response.longCount} LONG / ${response.shortCount} SHORT`;
        } else if (response.uploadError) {
            message = `⚠️ Scanned ${response.count} symbols, but upload failed: ${response.uploadError}. CSV downloaded locally.`;
        } else {
            const localNote = response.localOnly
                ? " — stored locally only (backend upload is OFF in Settings)"
                : "";
            message = `✅ ${response.message || "Done"}${localNote}`;
        }
        status.innerHTML = `<div>${message}</div><div class="progress-bar"><div class="fill" style="width:100%"></div></div>`;
    } catch (e) {
        console.error(e);
        status.innerHTML = `<div>❌ ${e.message || "Open a Sensibull tab first"}</div>`;
    } finally {
        chrome.runtime.onMessage.removeListener(progressListener);
        scanBtn.disabled = false;
        scanWlBtn.disabled = false;
        scanTodayBtn.disabled = false;
    }
}

// ========== DASHBOARD ==========
function renderDashboard(results) {
    if (!results || results.length === 0) return;

    const tbody = document.getElementById("dashBody");
    const dashTime = document.getElementById("dashTime");

    dashTime.textContent = `Last scan: ${new Date().toLocaleTimeString()} (${results.length} symbols)`;

    tbody.innerHTML = results.map(r => {
        if (r.error) return `<tr><td>${r.symbol}</td><td colspan="5" style="color:#ef5350">${r.error}</td></tr>`;

        const pcr = r.pcr ? r.pcr.toFixed(2) : "-";
        const pcrClass = r.pcr > 1.2 ? "bullish" : r.pcr < 0.8 ? "bearish" : "neutral";

        let signal = "Neutral";
        let signalClass = "neutral";
        if (r.SupportMigration > 0 && r.ResistanceMigration < 0) {
            signal = "Bullish";
            signalClass = "bullish";
        } else if (r.SupportMigration < 0 && r.ResistanceMigration > 0) {
            signal = "Bearish";
            signalClass = "bearish";
        } else if (r.pcr > 1.3) {
            signal = "Bullish";
            signalClass = "bullish";
        } else if (r.pcr < 0.7) {
            signal = "Bearish";
            signalClass = "bearish";
        }

        const callOI = r.totalCallOI ? formatNum(r.totalCallOI) : "-";
        const putOI = r.totalPutOI ? formatNum(r.totalPutOI) : "-";

        return `<tr>
            <td><strong>${r.symbol}</strong></td>
            <td>${r.spot || "-"}</td>
            <td class="${pcrClass}">${pcr}</td>
            <td class="bearish">${callOI}</td>
            <td class="bullish">${putOI}</td>
            <td class="${signalClass}"><span class="badge ${signalClass === 'bullish' ? 'green' : signalClass === 'bearish' ? 'red' : ''}">${signal}</span></td>
        </tr>`;
    }).join("");
}

function formatNum(n) {
    if (Math.abs(n) >= 10000000) return (n / 10000000).toFixed(1) + "Cr";
    if (Math.abs(n) >= 100000) return (n / 100000).toFixed(1) + "L";
    if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toString();
}

document.getElementById("exportCsvBtn").addEventListener("click", () => {
    if (!lastScanResults) return;
    // Trigger CSV download via the content script. The send can fail when the
    // active tab is not a Sensibull page or its content script is stale.
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
        const dashTime = document.getElementById("dashTime");
        chrome.tabs.sendMessage(
            tab.id,
            { action: "downloadCSV", results: lastScanResults },
            () => {
                const error = chrome.runtime.lastError;
                if (error) {
                    console.warn("CSV export failed:", error.message);
                    if (dashTime) {
                        dashTime.textContent = "⚠️ Open a Sensibull tab, refresh it (F5), then export again";
                    }
                    return;
                }
                if (dashTime) dashTime.textContent = "CSV downloaded";
            }
        );
    });
});

// ========== WATCHLIST (multiple named lists) ==========
async function getWatchlists() {
    const data = await chrome.storage.local.get(["watchlists", "activeWatchlist"]);
    let lists = data.watchlists;
    if (!lists || Object.keys(lists).length === 0) {
        lists = { "Default": [] };
    }
    const active = data.activeWatchlist && lists[data.activeWatchlist]
        ? data.activeWatchlist
        : Object.keys(lists)[0];
    return { lists, active };
}

async function loadWatchlistUI() {
    const { lists, active } = await getWatchlists();
    currentWatchlistName = active;

    // Populate dropdown
    const select = document.getElementById("watchlistSelect");
    select.innerHTML = Object.keys(lists).map(name =>
        `<option value="${name}" ${name === active ? "selected" : ""}>${name}</option>`
    ).join("");

    selectedSymbols = new Set(lists[active] || []);
    renderWatchlistGrid(ALL_SYMBOLS);
    refreshActiveWatchlistDropdown();
}

async function refreshActiveWatchlistDropdown() {
    // The dropdown on the Scan panel that selects which list "Scan Watchlist" uses
    const { lists, active } = await getWatchlists();
    const sel = document.getElementById("activeWatchlistSelect");
    if (sel) {
        sel.innerHTML = Object.keys(lists).map(name =>
            `<option value="${name}" ${name === active ? "selected" : ""}>${name} (${lists[name].length})</option>`
        ).join("");
    }
}

function renderWatchlistGrid(symbols) {
    const grid = document.getElementById("watchlistGrid");
    grid.innerHTML = symbols.map(s => {
        const sel = selectedSymbols.has(s) ? "selected" : "";
        return `<div class="watchlist-item ${sel}" data-symbol="${s}">${s}</div>`;
    }).join("");

    grid.querySelectorAll(".watchlist-item").forEach(item => {
        item.addEventListener("click", () => {
            const sym = item.dataset.symbol;
            if (selectedSymbols.has(sym)) {
                selectedSymbols.delete(sym);
                item.classList.remove("selected");
            } else {
                selectedSymbols.add(sym);
                item.classList.add("selected");
            }
            document.getElementById("selectedCount").textContent = `${selectedSymbols.size} selected`;
        });
    });

    document.getElementById("selectedCount").textContent = `${selectedSymbols.size} selected`;
}

document.getElementById("watchlistSelect").addEventListener("change", async (e) => {
    currentWatchlistName = e.target.value;
    const { lists } = await getWatchlists();
    selectedSymbols = new Set(lists[currentWatchlistName] || []);
    await chrome.storage.local.set({ activeWatchlist: currentWatchlistName });
    document.getElementById("symbolSearch").value = "";
    renderWatchlistGrid(ALL_SYMBOLS);
    refreshActiveWatchlistDropdown();
});

document.getElementById("newWatchlist").addEventListener("click", async () => {
    const name = prompt("Name for new watchlist (e.g. Banking, Index, High PCR):");
    if (!name || !name.trim()) return;
    const cleanName = name.trim();

    const { lists } = await getWatchlists();
    if (lists[cleanName]) {
        alert("A watchlist with that name already exists.");
        return;
    }
    lists[cleanName] = [];
    await chrome.storage.local.set({ watchlists: lists, activeWatchlist: cleanName });
    await loadWatchlistUI();
});

document.getElementById("deleteWatchlist").addEventListener("click", async () => {
    const { lists } = await getWatchlists();
    const names = Object.keys(lists);
    if (names.length <= 1) {
        alert("Cannot delete the last watchlist.");
        return;
    }
    if (!confirm(`Delete watchlist "${currentWatchlistName}"?`)) return;

    delete lists[currentWatchlistName];
    const newActive = Object.keys(lists)[0];
    await chrome.storage.local.set({ watchlists: lists, activeWatchlist: newActive });
    await loadWatchlistUI();
});

document.getElementById("symbolSearch").addEventListener("input", (e) => {
    const query = e.target.value.toUpperCase();
    const filtered = ALL_SYMBOLS.filter(s => s.includes(query));
    renderWatchlistGrid(filtered);
});

document.getElementById("selectAll").addEventListener("click", () => {
    if (selectedSymbols.size === ALL_SYMBOLS.length) {
        selectedSymbols.clear();
    } else {
        ALL_SYMBOLS.forEach(s => selectedSymbols.add(s));
    }
    renderWatchlistGrid(ALL_SYMBOLS);
});

document.getElementById("saveWatchlist").addEventListener("click", async () => {
    const { lists } = await getWatchlists();
    lists[currentWatchlistName] = [...selectedSymbols];
    await chrome.storage.local.set({ watchlists: lists, activeWatchlist: currentWatchlistName });
    refreshActiveWatchlistDropdown();
    document.getElementById("saveWatchlist").textContent = "✅ Saved!";
    setTimeout(() => { document.getElementById("saveWatchlist").textContent = "Save Watchlist"; }, 1500);
});

// ========== HISTORY ==========
async function loadHistory() {
    const data = await chrome.storage.local.get("scanHistory");
    const history = data.scanHistory || [];
    const list = document.getElementById("historyList");

    if (history.length === 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#78909c">No scan history yet</div>';
        return;
    }

    list.innerHTML = history.map((h, i) => {
        const date = new Date(h.timestamp).toLocaleString();
        return `<div class="history-item" data-index="${i}">
            <div style="display:flex;justify-content:space-between">
                <span class="count">${h.count} symbols</span>
                <span class="time">${date}</span>
            </div>
            <div style="font-size:11px;color:#78909c;margin-top:3px">
                Mode: ${h.mode || "intraday"} ${h.fromDate ? "| Date: " + h.fromDate : ""} ${h.expiry ? "| Exp: " + h.expiry : ""}
            </div>
        </div>`;
    }).join("");

    list.querySelectorAll(".history-item").forEach(item => {
        item.addEventListener("click", async () => {
            const data = await chrome.storage.local.get("scanHistory");
            const scan = data.scanHistory[item.dataset.index];
            if (scan && scan.results) {
                lastScanResults = scan.results;
                renderDashboard(scan.results);
                // Switch to dashboard tab
                document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
                document.querySelector('[data-tab="dashboard"]').classList.add("active");
                document.getElementById("panel-dashboard").classList.add("active");
            }
        });
    });
}

document.getElementById("clearHistory").addEventListener("click", async () => {
    await chrome.storage.local.set({ scanHistory: [] });
    loadHistory();
});

// ========== SETTINGS ==========
async function loadSettings() {
    const data = await chrome.storage.local.get(["schedules", "schedulesEnabled", "telegramConfig", "sheetsConfig", "backendConfig"]);

    // Schedules
    const schedules = data.schedules || [
        { id: "market_open", hour: 9, minute: 20, label: "Market Open" },
        { id: "mid_day", hour: 12, minute: 30, label: "Mid Day" },
        { id: "market_close", hour: 15, minute: 20, label: "Market Close" }
    ];

    document.getElementById("scheduleEnabled").checked = data.schedulesEnabled || false;

    const scheduleList = document.getElementById("scheduleList");
    scheduleList.innerHTML = schedules.map(s => `
        <div class="schedule-row">
            <span style="flex:1;font-size:12px">${s.label}</span>
            <input type="number" min="0" max="23" value="${s.hour}" data-id="${s.id}" class="sched-hour">
            <span>:</span>
            <input type="number" min="0" max="59" value="${s.minute}" data-id="${s.id}" class="sched-min">
            <span style="font-size:11px;color:#78909c">IST</span>
        </div>
    `).join("");

    // Telegram
    const tg = data.telegramConfig || { botToken: "", chatId: "", enabled: false };
    document.getElementById("telegramEnabled").checked = tg.enabled;
    document.getElementById("telegramToken").value = tg.botToken;
    document.getElementById("telegramChatId").value = tg.chatId;

    // Sheets
    const sheets = data.sheetsConfig || { sheetId: "", sheetName: "Sheet1" };
    document.getElementById("sheetId").value = sheets.sheetId || "";
    document.getElementById("sheetName").value = sheets.sheetName || "Sheet1";

    // Backend upload
    const backend = Object.assign(
        { baseUrl: "http://localhost:8000", collectorToken: "", uploadEnabled: false },
        data.backendConfig || {}
    );
    document.getElementById("uploadEnabled").checked = backend.uploadEnabled === true;
    document.getElementById("backendUrl").value = backend.baseUrl || "";
    document.getElementById("collectorToken").value = backend.collectorToken || "";
}

document.getElementById("saveSettings").addEventListener("click", async () => {
    // Collect schedules
    const schedules = [];
    document.querySelectorAll(".schedule-row").forEach(row => {
        const hourInput = row.querySelector(".sched-hour");
        const minInput = row.querySelector(".sched-min");
        const label = row.querySelector("span").textContent;
        schedules.push({
            id: hourInput.dataset.id,
            hour: parseInt(hourInput.value),
            minute: parseInt(minInput.value),
            label
        });
    });

    const schedulesEnabled = document.getElementById("scheduleEnabled").checked;
    const telegramConfig = {
        botToken: document.getElementById("telegramToken").value,
        chatId: document.getElementById("telegramChatId").value,
        enabled: document.getElementById("telegramEnabled").checked
    };
    const sheetsConfig = {
        sheetId: document.getElementById("sheetId").value,
        sheetName: document.getElementById("sheetName").value
    };
    const backendConfig = {
        baseUrl: document.getElementById("backendUrl").value.trim(),
        collectorToken: document.getElementById("collectorToken").value.trim(),
        uploadEnabled: document.getElementById("uploadEnabled").checked
    };

    await chrome.storage.local.set({ schedules, schedulesEnabled, telegramConfig, sheetsConfig, backendConfig });

    // Update alarms
    chrome.runtime.sendMessage({ action: "updateSchedules", schedules, enabled: schedulesEnabled });

    document.getElementById("saveSettings").textContent = "✅ Saved!";
    setTimeout(() => { document.getElementById("saveSettings").textContent = "Save All Settings"; }, 1500);
});

document.getElementById("testBackend").addEventListener("click", async () => {
    const btn = document.getElementById("testBackend");
    const status = document.getElementById("backendStatus");
    const config = {
        baseUrl: document.getElementById("backendUrl").value.trim(),
        collectorToken: document.getElementById("collectorToken").value.trim(),
        uploadEnabled: true
    };
    // Sai… save FIRST: a green "Connected" must never be possible while the
    // values are still unsaved. Test-without-save was a trap.
    await chrome.storage.local.set({ backendConfig: config });
    status.style.display = "block";
    status.textContent = "Saved ✓ — testing connection...";
    btn.textContent = "Testing...";
    try {
        const response = await chrome.runtime.sendMessage({ action: "testBackend", config });
        if (!response || response.ok === false) {
            throw new Error(response?.error || "Connection failed");
        }
        const storage = response.status?.storage_backend || "unknown";
        const scanner = response.status?.scanner_version || "unknown";
        const lastScan = response.status?.last_scan;
        const last = lastScan ? `${lastScan.status} at ${new Date(lastScan.started_at).toLocaleString()}` : "none";
        status.textContent = `✅ Saved & connected · storage: ${storage} · scanner: ${scanner} · last scan: ${last}`;
        btn.textContent = "✅ Connected";
    } catch (error) {
        status.textContent = `❌ ${error?.message || "Connection failed"} (values were saved — fix URL/token and test again)`;
        btn.textContent = "❌ Failed";
    }
    setTimeout(() => { btn.textContent = "Test Connection"; }, 2500);
});

document.getElementById("testTelegram").addEventListener("click", async () => {
    const config = {
        botToken: document.getElementById("telegramToken").value,
        chatId: document.getElementById("telegramChatId").value
    };
    const btn = document.getElementById("testTelegram");
    btn.textContent = "Sending...";

    chrome.runtime.sendMessage({
        action: "sendTelegram",
        config,
        message: "🔍 <b>Sensibull OI Scanner</b>\n\nTest message - Telegram integration working! ✅"
    }, (response) => {
        btn.textContent = response?.success ? "✅ Sent!" : "❌ Failed";
        setTimeout(() => { btn.textContent = "Test Message"; }, 2000);
    });
});

document.getElementById("exportSheets").addEventListener("click", async () => {
    const btn = document.getElementById("exportSheets");
    if (!lastScanResults) {
        btn.textContent = "❌ No scan data";
        setTimeout(() => { btn.textContent = "Export Last Scan to Sheets"; }, 2000);
        return;
    }
    btn.textContent = "⏳ Exporting...";

    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const data = await chrome.storage.local.get("sheetsConfig");
        chrome.tabs.sendMessage(tab.id, {
            action: "exportToSheets",
            results: lastScanResults,
            config: data.sheetsConfig
        });
        btn.textContent = "✅ Exported!";
    } catch (e) {
        btn.textContent = "❌ " + e.message;
    }
    setTimeout(() => { btn.textContent = "Export Last Scan to Sheets"; }, 2000);
});

// ========== TELEGRAM SUMMARY ==========
async function sendTelegramSummary(results) {
    const data = await chrome.storage.local.get("telegramConfig");
    const config = data.telegramConfig;
    if (!config || !config.enabled || !config.botToken || !config.chatId) return;

    const bullish = results.filter(r => !r.error && r.pcr > 1.2);
    const bearish = results.filter(r => !r.error && r.pcr < 0.8);

    let msg = `🔍 <b>OI Scan Complete</b>\n`;
    msg += `📊 ${results.length} symbols scanned\n`;
    msg += `🟢 Bullish (PCR>1.2): ${bullish.length}\n`;
    msg += `🔴 Bearish (PCR<0.8): ${bearish.length}\n\n`;

    if (bullish.length > 0) {
        msg += `<b>Top Bullish:</b>\n`;
        bullish.sort((a, b) => b.pcr - a.pcr).slice(0, 5).forEach(r => {
            msg += `  • ${r.symbol} PCR: ${r.pcr.toFixed(2)}\n`;
        });
    }

    if (bearish.length > 0) {
        msg += `\n<b>Top Bearish:</b>\n`;
        bearish.sort((a, b) => a.pcr - b.pcr).slice(0, 5).forEach(r => {
            msg += `  • ${r.symbol} PCR: ${r.pcr.toFixed(2)}\n`;
        });
    }

    chrome.runtime.sendMessage({ action: "sendTelegram", config, message: msg });
}

// ========== INIT ==========
loadWatchlistUI();
refreshActiveWatchlistDropdown();
