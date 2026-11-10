console.log("Sensibull Scanner v3.1 Loaded");

const ALL_SYMBOLS = `
NIFTY
BANKNIFTY
ABCAPITAL
ADANIENSOL
GODFRYPHLP
INDHOTEL
INDIANB
INOXWIND
JINDALSTEL
MPHASIS
NESTLEIND
NTPC
PRESTIGE
RBLBANK
SHREECEM
TATAELXSI
TATASTEEL
TCS
ADANIPOWER
AMBUJACEM
APLAPOLLO
AUROPHARMA
BAJAJHLDNG
BSE
CDSL
CONCOR
DALBHARAT
EICHERMOT
INDIGO
JIOFIN
KAYNES
KEI
MFSL
NYKAA
PAGEIND
PERSISTENT
PNBHOUSING
SBILIFE
TIINDIA
TITAN
TRENT
UNIONBANK
YESBANK
ABB
BDL
BEL
BHEL
CGPOWER
GMRAIRPORT
HAL
HCLTECH
JUBLFOOD
OBEROIRLTY
ONGC
PNB
POWERGRID
SONACOMS
AXISBANK
COCHINSHIP
ETERNAL
GVT&D
HINDPETRO
IDFCFIRSTB
LODHA
TVSMOTOR
BAJAJ-AUTO
BOSCHLTD
CIPLA
DLF
DRREDDY
EXIDEIND
GODREJPROP
KOTAKBANK
M&M
NATIONALUM
NHPC
PAYTM
PGEL
TECHM
ULTRACEMCO
BANKINDIA
BIOCON
COALINDIA
COLPAL
FEDERALBNK
FORCEMOT
GODREJCP
KPITTECH
LT
NMDC
OIL
PHOENIXLTD
PIIND
TATACONSUM
WIPRO
BHARATFORG
CROMPTON
INDUSTOWER
NAM-INDIA
PATANJALI
POWERINDIA
SOLARINDS
TATAPOWER
VOLTAS
APOLLOHOSP
DELHIVERY
DIXON
FORTIS
GLENMARK
HINDUNILVR
ICICIPRULI
IDEA
NBCC
POLYCAB
ALKEM
ASHOKLEY
ASTRAL
BANKBARODA
BHARTIARTL
BPCL
CHOLAFIN
CUMMINSIND
DIVISLAB
IEX
INDUSINDBK
JSWENERGY
KALYANKJIL
LAURUSLABS
LTF
MANAPPURAM
MARICO
MOTHERSON
MOTILALOFS
RELIANCE
SRF
SWIGGY
VMM
ZYDUSLIFE
ADANIGREEN
ADANIPORTS
BAJAJFINSV
BLUESTARCO
DABUR
HDFCAMC
IOC
ITC
MAXHEALTH
OFSS
PIDILITIND
SBIN
360ONE
ADANIENT
JSWSTEEL
LICI
POLICYBZR
PREMIERENE
SAIL
SUZLON
UPL
VEDL
ASIANPAINT
BRITANNIA
GRASIM
HDFCLIFE
ICICIBANK
ICICIGI
INFY
KFINTECH
MARUTI
MUTHOOTFIN
PFC
SAMMAANCAP
SUNPHARMA
SUPREMEIND
UNOMINDA
COFORGE
GAIL
HAVELLS
HDFCBANK
HEROMOTOCO
MANKIND
MAZDOCK
MCX
NUVAMA
PETRONET
SIEMENS
UNITDSPR
AMBER
BAJFINANCE
CANBK
DMART
HINDZINC
IREDA
LICHSGFIN
LTM
LUPIN
RADICO
RVNL
SHRIRAMFIN
TMPV
ANGELONE
AUBANK
BANDHANBNK
CAMS
HINDALCO
HYUNDAI
IRFC
NAUKRI
RECLTD
SBICARD
TORNTPHARM
WAAREEENER
VBL
`.trim().split("\n").map(s => s.trim()).filter(Boolean);

console.log(`Loaded ${ALL_SYMBOLS.length} symbols`);

function categorizeStrikes(atmStrike, strikeList, depth = 5) {
    strikeList = strikeList.map(Number).sort((a, b) => a - b);
    const atmIndex = strikeList.indexOf(Number(atmStrike));

    const result = { ATM: strikeList[atmIndex], CE: {}, PE: {} };

    for (let i = 1; i <= depth; i++) {
        // CE: ITM is below ATM, OTM is above ATM
        result.CE[`ITM${i}`] = strikeList[atmIndex - i] ?? null;
        result.CE[`OTM${i}`] = strikeList[atmIndex + i] ?? null;
        // PE: ITM is above ATM, OTM is below ATM
        result.PE[`ITM${i}`] = strikeList[atmIndex + i] ?? null;
        result.PE[`OTM${i}`] = strikeList[atmIndex - i] ?? null;
    }

    return result;
}

async function scanSymbol(symbol, options = {}) {
    const { fromDate = null, toDate = null, mode = "intraday", expiry = null, depth = 5 } = options;

    try {
        const expiries = expiry
            ? { [expiry]: { is_weekly: true, is_enabled: true } }
            : {};

        const requestPayload = {
            underlying: symbol,
            mode: mode,
            expiries: expiries,
            atm_strike_selection: "ten",
            input_min_strike: null,
            input_max_strike: null,
            from_time: null,
            to_time: null,
            auto_update: "full_day",
            from_date: fromDate,
            to_date: toDate,
            show_oi: false
        };

        const response = await fetch(
            "https://oxide.sensibull.com/v1/compute/1/oi_graphs/oi_change_chart",
            {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    "x-device-id": "83bc2e49-de14-45bc-91cb-ede7c156b16f",
                    "frt-ref": Math.random().toString(36).substring(2)
                },
                body: JSON.stringify(requestPayload)
            }
        );

        if (response.status === 429) {
            return { symbol, error: "Rate limited (429)" };
        }

        const json = await response.json();

        if (!json.success || !json.payload) {
            return { symbol, error: "No data returned" };
        }

        const responseData = json.payload;
        const strikeMap = categorizeStrikes(responseData.atm_strike, responseData.strike_list, depth);
        const perStrike = responseData.per_strike_data || {};
        const bucketData = {};

        // ATM
        const atmStrikeData = perStrike[strikeMap.ATM] || {};
        bucketData.ATM = {
            strike: strikeMap.ATM,
            callOiChange: atmStrikeData.call_oi_change ?? 0,
            putOiChange: atmStrikeData.put_oi_change ?? 0
        };

        // CE Buckets
        Object.entries(strikeMap.CE).forEach(([bucket, strike]) => {
            if (!strike) return;
            const strikeData = perStrike[strike] || {};
            bucketData[`CE_${bucket}`] = { strike, callOiChange: strikeData.call_oi_change ?? 0 };
        });

        // PE Buckets
        Object.entries(strikeMap.PE).forEach(([bucket, strike]) => {
            if (!strike) return;
            const strikeData = perStrike[strike] || {};
            bucketData[`PE_${bucket}`] = { strike, putOiChange: strikeData.put_oi_change ?? 0 };
        });

        // Research Fields (uses first 3 strikes)
        bucketData.ITM_PE_Total = (bucketData.PE_ITM1?.putOiChange || 0) + (bucketData.PE_ITM2?.putOiChange || 0) + (bucketData.PE_ITM3?.putOiChange || 0);
        bucketData.OTM_PE_Total = (bucketData.PE_OTM1?.putOiChange || 0) + (bucketData.PE_OTM2?.putOiChange || 0) + (bucketData.PE_OTM3?.putOiChange || 0);
        bucketData.ITM_CE_Total = (bucketData.CE_ITM1?.callOiChange || 0) + (bucketData.CE_ITM2?.callOiChange || 0) + (bucketData.CE_ITM3?.callOiChange || 0);
        bucketData.OTM_CE_Total = (bucketData.CE_OTM1?.callOiChange || 0) + (bucketData.CE_OTM2?.callOiChange || 0) + (bucketData.CE_OTM3?.callOiChange || 0);
        bucketData.SupportMigration = bucketData.ITM_PE_Total - bucketData.OTM_PE_Total;
        bucketData.ResistanceMigration = bucketData.ITM_CE_Total - bucketData.OTM_CE_Total;

        return {
            symbol,
            spot: responseData.current_ltp,
            pcr: responseData.pcr,
            totalCallOI: responseData.total_call_oi_change,
            totalPutOI: responseData.total_put_oi_change,
            depth,
            ...bucketData
        };
    } catch (err) {
        console.error(symbol, err);
        return { symbol, error: err.message };
    }
}

function downloadCSV(rows, options = {}) {
    if (!globalThis.SensibullCsv) {
        console.error("CSV builder is not loaded");
        return;
    }
    const csv = globalThis.SensibullCsv.buildCSV(rows, options);
    const filename = globalThis.SensibullCsv.buildFileName(options);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function getDatesBetween(startDate, endDate) {
    const dates = [];
    const current = new Date(startDate);
    const end = new Date(endDate);
    while (current <= end) {
        const yyyy = current.getFullYear();
        const mm = String(current.getMonth() + 1).padStart(2, "0");
        const dd = String(current.getDate()).padStart(2, "0");
        dates.push(`${yyyy}-${mm}-${dd}`);
        current.setDate(current.getDate() + 1);
    }
    return dates;
}

async function runScanner(options = {}) {
    const { fromDate, toDate, symbols: customSymbols, reportProgress, scanId, skipDownload } = options;
    const symbols = customSymbols || ALL_SYMBOLS;
    const delayMs = options.delayMs ?? 1000;
    const maxRetries = options.maxRetries ?? 1;

    const dates = (fromDate && toDate) ? getDatesBetween(fromDate, toDate) : [null];
    let totalScanned = 0;
    let allResults = [];

    for (const date of dates) {
        const dayOptions = { ...options };
        if (date) {
            dayOptions.fromDate = date;
            dayOptions.toDate = date;
        }

        const results = [];

        for (let i = 0; i < symbols.length; i++) {
            const symbol = symbols[i];

            if (reportProgress) {
                chrome.runtime.sendMessage({
                    action: "scanProgress",
                    current: i + 1,
                    total: symbols.length,
                    symbol,
                    date: date || "today",
                    scanId: scanId || null
                });
            }

            console.log(`[${date || "today"}] Scanning ${i + 1}/${symbols.length}: ${symbol}`);
            const result = await scanSymbol(symbol, dayOptions);
            results.push(result);

            await new Promise(resolve => setTimeout(resolve, delayMs));
        }

        // Retry failed symbols
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            const failedIndexes = results
                .map((r, idx) => (r.error ? idx : -1))
                .filter(idx => idx !== -1);

            if (failedIndexes.length === 0) break;

            console.log(`Retry attempt ${attempt}: ${failedIndexes.length} failed symbols`);

            for (let j = 0; j < failedIndexes.length; j++) {
                const idx = failedIndexes[j];
                const symbol = results[idx].symbol;

                if (reportProgress) {
                    chrome.runtime.sendMessage({
                        action: "scanProgress",
                        current: j + 1,
                        total: failedIndexes.length,
                        symbol: `🔄 ${symbol} (retry ${attempt})`,
                        date: date || "today",
                        scanId: scanId || null
                    });
                }

                // Retries wait a bit longer to dodge rate limits
                await new Promise(resolve => setTimeout(resolve, delayMs + 500));
                const retryResult = await scanSymbol(symbol, dayOptions);
                if (!retryResult.error) {
                    results[idx] = retryResult;
                }
            }
        }

        if (!skipDownload) {
            downloadCSV(results, dayOptions);
        }
        allResults = allResults.concat(results);
        totalScanned += results.length;
    }

    if (reportProgress) {
        chrome.runtime.sendMessage({
            action: "scanComplete",
            results: allResults,
            scanId: scanId || null
        });
    }

    return { totalScanned, results: allResults };
}

// Message listener
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("Received message:", request);

    if (request.action === "runScan") {
        const options = {
            fromDate: request.fromDate || null,
            toDate: request.toDate || null,
            mode: request.mode || "intraday",
            expiry: request.expiry || null,
            symbols: request.symbols || null,
            reportProgress: request.reportProgress || false,
            delayMs: request.delayMs ?? 1000,
            depth: request.depth ?? 5,
            maxRetries: request.maxRetries ?? 1,
            scanId: request.scanId || null,
            skipDownload: request.skipDownload === true
        };

        runScanner(options)
            .then(result => sendResponse({
                message: `Completed ${result.totalScanned} symbols`,
                results: result.results
            }))
            .catch(error => {
                console.error(error);
                sendResponse({ message: error.message, error: true, results: [] });
            });

        return true;
    }

    if (request.action === "downloadCSV") {
        downloadCSV(request.results, request.options || {});
        sendResponse({ success: true });
    }
});
