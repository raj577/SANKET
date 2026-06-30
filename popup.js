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

// ========== SCAN PANEL ==========

document.getElementById("scanTodayBtn").addEventListener("click", () => startScan(false, true));
document.getElementById("scanBtn").addEventListener("click", () => startScan(false));
document.getElementById("scanWatchlistBtn").addEventListener("click", () => startScan(true));

async function startScan(watchlistOnly, todayOnly = false) {
    const status = document.getElementById("status");
    const progressFill = document.getElementById("progressFill");
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

    let symbolsToScan = ALL_SYMBOLS;
    if (watchlistOnly) {
        const data = await chrome.storage.local.get("watchlist");
        symbolsToScan = data.watchlist && data.watchlist.length > 0 ? data.watchlist : ALL_SYMBOLS;
    }

    status.innerHTML = `<div>Starting scan of ${symbolsToScan.length} symbols...</div><div class="progress-bar"><div class="fill" id="progressFill"></div></div>`;

    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

        // Listen for progress updates
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
                // Save to history
                chrome.runtime.sendMessage({
                    action: "saveScanHistory",
                    scanData: {
                        count: message.results.length,
                        mode, fromDate, toDate, expiry,
                        results: message.results
                    }
                });
                // Send telegram if enabled
                sendTelegramSummary(message.results);
            }
        };

        chrome.runtime.onMessage.addListener(progressListener);

        const response = await chrome.tabs.sendMessage(tab.id, {
            action: "runScan",
            fromDate, toDate, mode, expiry,
            symbols: symbolsToScan,
            reportProgress: true
        });

        status.innerHTML = `<div>✅ ${response?.message || "Done"}</div><div class="progress-bar"><div class="fill" style="width:100%"></div></div>`;

        chrome.runtime.onMessage.removeListener(progressListener);

    } catch (e) {
        console.error(e);
        status.innerHTML = `<div>❌ ${e.message || "Open a Sensibull tab first"}</div>`;
    }

    scanBtn.disabled = false;
    scanWlBtn.disabled = false;
    scanTodayBtn.disabled = false;
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
    // Trigger CSV download via content script
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
        chrome.tabs.sendMessage(tab.id, { action: "downloadCSV", results: lastScanResults });
    });
});

// ========== WATCHLIST ==========
async function loadWatchlistUI() {
    const data = await chrome.storage.local.get("watchlist");
    const watchlist = data.watchlist || [];
    selectedSymbols = new Set(watchlist);
    renderWatchlistGrid(ALL_SYMBOLS);
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
    await chrome.storage.local.set({ watchlist: [...selectedSymbols] });
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
    const data = await chrome.storage.local.get(["schedules", "schedulesEnabled", "telegramConfig", "sheetsConfig"]);

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

    await chrome.storage.local.set({ schedules, schedulesEnabled, telegramConfig, sheetsConfig });

    // Update alarms
    chrome.runtime.sendMessage({ action: "updateSchedules", schedules, enabled: schedulesEnabled });

    document.getElementById("saveSettings").textContent = "✅ Saved!";
    setTimeout(() => { document.getElementById("saveSettings").textContent = "Save All Settings"; }, 1500);
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
