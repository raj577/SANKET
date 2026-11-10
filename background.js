// Background service worker for scheduled scans, backend upload and notifications
importScripts("csv-utils.js", "api-client.js");

// Default scheduled scan times (IST: 9:20, 12:30, 15:20)
const DEFAULT_SCHEDULES = [
    { id: "market_open", hour: 9, minute: 20, label: "Market Open" },
    { id: "mid_day", hour: 12, minute: 30, label: "Mid Day" },
    { id: "market_close", hour: 15, minute: 20, label: "Market Close" }
];

const DEFAULT_BACKEND_CONFIG = {
    baseUrl: "http://localhost:8000",
    collectorToken: "",
    uploadEnabled: false
};

// Initialize alarms on install
chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.local.get("schedules", (data) => {
        if (!data.schedules) {
            chrome.storage.local.set({ schedules: DEFAULT_SCHEDULES, schedulesEnabled: false });
        }
    });
    chrome.storage.local.get(["watchlists", "watchlist"], (data) => {
        if (!data.watchlists) {
            // Migrate old single watchlist if it exists
            const migrated = data.watchlist && data.watchlist.length > 0
                ? { "Default": data.watchlist }
                : { "Default": [] };
            chrome.storage.local.set({ watchlists: migrated, activeWatchlist: "Default" });
        }
    });
    chrome.storage.local.get("telegramConfig", (data) => {
        if (!data.telegramConfig) {
            chrome.storage.local.set({ telegramConfig: { botToken: "", chatId: "", enabled: false } });
        }
    });
    chrome.storage.local.get("scanHistory", (data) => {
        if (!data.scanHistory) {
            chrome.storage.local.set({ scanHistory: [] });
        }
    });
    chrome.storage.local.get("backendConfig", (data) => {
        if (!data.backendConfig) {
            chrome.storage.local.set({ backendConfig: DEFAULT_BACKEND_CONFIG });
        }
    });
});

// Handle alarm triggers
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name.startsWith("scan_")) {
        triggerScheduledScan(alarm.name);
    }
});

async function getBackendConfig() {
    const data = await chrome.storage.local.get("backendConfig");
    const config = Object.assign({}, DEFAULT_BACKEND_CONFIG, data.backendConfig || {});
    config.baseUrl = String(config.baseUrl || "").trim();
    config.collectorToken = String(config.collectorToken || "").trim();
    config.uploadEnabled = config.uploadEnabled === true;
    return config;
}

async function findTargetTab(preferredTabId) {
    if (Number.isInteger(preferredTabId)) {
        try {
            const tab = await chrome.tabs.get(preferredTabId);
            if (tab && /^https:\/\/web\.sensibull\.com\//.test(tab.url || "")) return tab;
        } catch (error) {
            // Fall through to a URL query.
        }
    }
    const tabs = await chrome.tabs.query({ url: "https://web.sensibull.com/*" });
    return tabs.length > 0 ? tabs[0] : null;
}

const MESSAGING_ERROR_FRAGMENTS = [
    "could not establish connection",
    "receiving end does not exist",
    "message port closed",
    "extension context invalidated"
];

function isMessagingError(error) {
    const message = String(error?.message || error || "").toLowerCase();
    return MESSAGING_ERROR_FRAGMENTS.some((fragment) => message.includes(fragment));
}

/**
 * Tabs opened before the extension was installed or reloaded have no content
 * script ("Receiving end does not exist"). Injecting the same files the
 * manifest would inject on page load recovers without a manual refresh.
 */
async function ensureContentScript(tabId) {
    await chrome.scripting.executeScript({
        target: { tabId },
        files: ["csv-utils.js", "content.js"]
    });
    // Give the injected listener a beat to register.
    await new Promise((resolve) => setTimeout(resolve, 120));
}

async function requestLocalDownload(tabId, results, options) {
    try {
        await chrome.tabs.sendMessage(tabId, {
            action: "downloadCSV",
            results,
            options: {
                fromDate: options?.fromDate || null,
                expiry: options?.expiry || null,
                depth: options?.depth || null
            }
        });
    } catch (error) {
        console.warn("Local CSV download failed after upload error:", error?.message || error);
    }
}

async function safeComplete(api, scanId, status, errorMessage) {
    try {
        await api.completeScan(scanId, {
            status,
            error_message: errorMessage || null
        });
    } catch (error) {
        console.warn("Marking scan failed on the backend also failed:", error?.message || error);
    }
}

/**
 * Runs one scan end-to-end.
 *
 * When backend upload is enabled the CSV is created here (service worker),
 * archived by the backend, and scanned into candidates before completion.
 * The original data is never lost: a failed upload triggers the normal local
 * CSV download as a fallback.
 */
async function orchestrateScan(options = {}, preferredTabId = null) {
    const tab = await findTargetTab(preferredTabId);
    if (!tab) {
        throw new Error("Open a Sensibull tab first");
    }

    const config = await getBackendConfig();
    const upload = config.uploadEnabled === true;

    if (upload && (!config.baseUrl || !config.collectorToken)) {
        throw new Error("Backend upload is enabled but the URL or collector token is missing");
    }

    let api = null;
    let scanId = null;
    if (upload) {
        api = new SensibullApi(config);
        scanId = crypto.randomUUID();
        const totalSymbols = Array.isArray(options.symbols) ? options.symbols.length : 0;
        await api.createScan(scanId, totalSymbols, new Date().toISOString(), options.trigger || "extension");
    }

    const scanPayload = {
        action: "runScan",
        fromDate: options.fromDate || null,
        toDate: options.toDate || null,
        mode: options.mode || "intraday",
        expiry: options.expiry || null,
        symbols: options.symbols || null,
        delayMs: options.delayMs ?? 1000,
        depth: options.depth ?? 5,
        maxRetries: options.maxRetries ?? 1,
        reportProgress: true,
        scanId,
        skipDownload: upload
    };

    let response;
    try {
        response = await chrome.tabs.sendMessage(tab.id, scanPayload);
    } catch (error) {
        if (!isMessagingError(error)) {
            if (api && scanId) {
                await safeComplete(api, scanId, "FAILED", "Lost contact with the Sensibull tab: " + (error?.message || error));
            }
            throw new Error("Scan failed: " + (error?.message || "the Sensibull tab did not respond"));
        }
        // Dead content script: inject and retry once before blaming the user.
        try {
            await ensureContentScript(tab.id);
            response = await chrome.tabs.sendMessage(tab.id, scanPayload);
        } catch (retryError) {
            const reason = retryError?.message || error?.message || "no listener in the Sensibull tab";
            if (api && scanId) {
                await safeComplete(api, scanId, "FAILED", "Sensibull tab not reachable: " + reason);
            }
            throw new Error(
                "The Sensibull tab was opened before the extension loaded. " +
                "Refresh the Sensibull tab (F5) and run the scan again. (" + reason + ")"
            );
        }
    }

    if (!response || response.error) {
        const message = response?.message || "The scan did not complete";
        if (api && scanId) {
            await safeComplete(api, scanId, "FAILED", message);
        }
        throw new Error(message);
    }

    const results = Array.isArray(response.results) ? response.results : [];
    const summary = globalThis.SensibullCsv.summarize(results);

    if (!upload) {
        return {
            ok: true,
            upload: false,
            localOnly: true,
            count: results.length,
            message: response.message || `Completed ${results.length} symbols`
        };
    }

    const csvText = globalThis.SensibullCsv.buildCSV(results, options);
    const filename = globalThis.SensibullCsv.buildFileName(options);

    try {
        const uploaded = await api.uploadCsv(scanId, csvText, {
            filename,
            total: summary.total,
            successful: summary.successful,
            failed: summary.failed
        });

        const completionStatus = uploaded.status === "FAILED"
            ? "FAILED"
            : uploaded.status === "PARTIAL"
                ? "PARTIAL"
                : "COMPLETED";

        let finalScan = uploaded;
        try {
            finalScan = await api.completeScan(scanId, {
                status: completionStatus,
                successful_symbols: summary.successful,
                failed_symbols: summary.failed,
                error_message: uploaded.error_message || null
            });
        } catch (error) {
            // The CSV is archived server-side even if this idempotent completion call fails.
            console.warn("Final completion call failed:", error?.message || error);
        }

        return {
            ok: true,
            upload: true,
            scanId,
            status: finalScan.status || uploaded.status,
            count: results.length,
            longCount: uploaded.long_candidates_count ?? 0,
            shortCount: uploaded.short_candidates_count ?? 0,
            csvFilename: uploaded.csv_filename || filename,
            message: response.message || `Completed ${results.length} symbols`
        };
    } catch (error) {
        const message = error?.message || String(error);
        await safeComplete(api, scanId, "FAILED", "CSV upload failed: " + message);
        await requestLocalDownload(tab.id, results, options);
        return {
            ok: true,
            upload: false,
            uploadError: message,
            scanId,
            count: results.length,
            message: response.message || `Completed ${results.length} symbols`
        };
    }
}

async function testBackend(config) {
    const api = new SensibullApi(config);
    const health = await api.health();
    const status = await api.getStatus();
    return { ok: true, health, status };
}

// Best-effort progress relay. If the service worker restarts, the next
// symbol's message simply resumes the updates.
const progressSentAt = new Map();

async function forwardProgress(message) {
    if (!message || !message.scanId) return;
    const now = Date.now();
    const last = progressSentAt.get(message.scanId) || 0;
    if (now - last < 2000 && message.current < message.total) return;
    progressSentAt.set(message.scanId, now);

    try {
        const config = await getBackendConfig();
        if (!config.uploadEnabled) return;
        const api = new SensibullApi(config);
        await api.reportProgress(message.scanId, {
            current_symbol: message.symbol,
            total_symbols: message.total
        });
    } catch (error) {
        console.warn("Progress update failed:", error?.message || error);
    }
}

async function triggerScheduledScan(alarmName) {
    const data = await chrome.storage.local.get(["schedulesEnabled"]);
    if (!data.schedulesEnabled) return;

    try {
        const result = await orchestrateScan({
            mode: "intraday",
            trigger: "scheduled",
            delayMs: 1000,
            depth: 5,
            maxRetries: 1
        });
        const suffix = result.upload
            ? `${result.status}: ${result.count} symbols, ${result.longCount} LONG / ${result.shortCount} SHORT`
            : `${result.count} symbols (stored locally)`;
        chrome.notifications.create({
            type: "basic",
            iconUrl: "icon48.png",
            title: "Sensibull OI Scanner",
            message: `Scheduled scan complete (${alarmName}): ${suffix}`
        });
    } catch (error) {
        chrome.notifications.create({
            type: "basic",
            iconUrl: "icon48.png",
            title: "Sensibull OI Scanner",
            message: `Scheduled scan failed (${alarmName}): ${error?.message || error}`
        });
    }
}

// Set up alarms based on schedules
function setupAlarms(schedules, enabled) {
    chrome.alarms.getAll((alarms) => {
        alarms.forEach((a) => {
            if (a.name.startsWith("scan_")) {
                chrome.alarms.clear(a.name);
            }
        });
    });

    if (!enabled) return;

    schedules.forEach((schedule) => {
        const now = new Date();
        const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
        const target = new Date(ist);
        target.setHours(schedule.hour, schedule.minute, 0, 0);

        if (target <= ist) {
            target.setDate(target.getDate() + 1);
        }

        const delayMs = target.getTime() - ist.getTime();
        chrome.alarms.create(`scan_${schedule.id}`, {
            delayInMinutes: delayMs / 60000,
            periodInMinutes: 24 * 60
        });
    });
}

// Listen for messages from popup/content
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "updateSchedules") {
        setupAlarms(request.schedules, request.enabled);
        sendResponse({ success: true });
        return false;
    }

    if (request.action === "orchestrateScan") {
        orchestrateScan(request.options || {}, request.tabId)
            .then((result) => sendResponse(result))
            .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
        return true;
    }

    if (request.action === "testBackend") {
        testBackend(request.config || {})
            .then((result) => sendResponse(result))
            .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
        return true;
    }

    if (request.action === "scanProgress") {
        forwardProgress(request);
        return false;
    }

    if (request.action === "sendTelegram") {
        sendTelegramMessage(request.config, request.message)
            .then(() => sendResponse({ success: true }))
            .catch((e) => sendResponse({ success: false, error: e.message }));
        return true;
    }

    if (request.action === "saveScanHistory") {
        saveScanHistory(request.scanData);
        sendResponse({ success: true });
    }
    return false;
});

async function sendTelegramMessage(config, message) {
    if (!config.botToken || !config.chatId) throw new Error("Telegram not configured");

    const url = `https://api.telegram.org/bot${config.botToken}/sendMessage`;
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            chat_id: config.chatId,
            text: message,
            parse_mode: "HTML"
        })
    });

    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.description || "Telegram API error");
    }
}

async function saveScanHistory(scanData) {
    const data = await chrome.storage.local.get("scanHistory");
    const history = data.scanHistory || [];

    history.unshift({
        timestamp: new Date().toISOString(),
        ...scanData
    });

    // Keep only last 50 scans
    if (history.length > 50) history.length = 50;

    await chrome.storage.local.set({ scanHistory: history });
}
