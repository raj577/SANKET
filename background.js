// Background service worker for scheduled scans and notifications

// Default scheduled scan times (IST: 9:20, 12:30, 15:20)
const DEFAULT_SCHEDULES = [
    { id: "market_open", hour: 9, minute: 20, label: "Market Open" },
    { id: "mid_day", hour: 12, minute: 30, label: "Mid Day" },
    { id: "market_close", hour: 15, minute: 20, label: "Market Close" }
];

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
});

// Handle alarm triggers
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name.startsWith("scan_")) {
        triggerScheduledScan(alarm.name);
    }
});

async function triggerScheduledScan(alarmName) {
    const data = await chrome.storage.local.get(["schedulesEnabled"]);
    if (!data.schedulesEnabled) return;

    // Find active sensibull tab and trigger scan
    const tabs = await chrome.tabs.query({ url: "https://web.sensibull.com/*" });
    if (tabs.length > 0) {
        chrome.tabs.sendMessage(tabs[0].id, {
            action: "runScan",
            mode: "intraday",
            scheduled: true
        });
        chrome.notifications.create({
            type: "basic",
            iconUrl: "icon48.png",
            title: "Sensibull OI Scanner",
            message: `Scheduled scan triggered: ${alarmName}`
        });
    }
}

// Set up alarms based on schedules
function setupAlarms(schedules, enabled) {
    // Clear existing scan alarms
    chrome.alarms.getAll((alarms) => {
        alarms.forEach(a => {
            if (a.name.startsWith("scan_")) {
                chrome.alarms.clear(a.name);
            }
        });
    });

    if (!enabled) return;

    schedules.forEach(schedule => {
        // Calculate next occurrence
        const now = new Date();
        const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
        let target = new Date(ist);
        target.setHours(schedule.hour, schedule.minute, 0, 0);

        if (target <= ist) {
            target.setDate(target.getDate() + 1);
        }

        const delayMs = target.getTime() - ist.getTime();
        const delayMin = delayMs / 60000;

        chrome.alarms.create(`scan_${schedule.id}`, {
            delayInMinutes: delayMin,
            periodInMinutes: 24 * 60
        });
    });
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "updateSchedules") {
        setupAlarms(request.schedules, request.enabled);
        sendResponse({ success: true });
    }

    if (request.action === "sendTelegram") {
        sendTelegramMessage(request.config, request.message)
            .then(r => sendResponse({ success: true }))
            .catch(e => sendResponse({ success: false, error: e.message }));
        return true;
    }

    if (request.action === "saveScanHistory") {
        saveScanHistory(request.scanData);
        sendResponse({ success: true });
    }
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
