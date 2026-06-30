console.log("Sensibull Scanner Loaded");

const symbols = `
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
`
    .trim()
    .split("\n")
    .map(s => s.trim())
    .filter(Boolean);

alert("Content Script Loaded");

console.log(`Loaded ${symbols.length} symbols`);

function categorizeStrikes(atmStrike, strikeList) {

    strikeList = strikeList
        .map(Number)
        .sort((a, b) => a - b);

    const atmIndex =
        strikeList.indexOf(Number(atmStrike));

    return {

        ATM:
            strikeList[atmIndex],

        CE: {

            ITM1: strikeList[atmIndex - 1] ?? null,
            ITM2: strikeList[atmIndex - 2] ?? null,
            ITM3: strikeList[atmIndex - 3] ?? null,
            ITM4: strikeList[atmIndex - 4] ?? null,
            ITM5: strikeList[atmIndex - 5] ?? null,

            OTM1: strikeList[atmIndex + 1] ?? null,
            OTM2: strikeList[atmIndex + 2] ?? null,
            OTM3: strikeList[atmIndex + 3] ?? null,
            OTM4: strikeList[atmIndex + 4] ?? null,
            OTM5: strikeList[atmIndex + 5] ?? null
        },

        PE: {

            ITM1: strikeList[atmIndex + 1] ?? null,
            ITM2: strikeList[atmIndex + 2] ?? null,
            ITM3: strikeList[atmIndex + 3] ?? null,
            ITM4: strikeList[atmIndex + 4] ?? null,
            ITM5: strikeList[atmIndex + 5] ?? null,

            OTM1: strikeList[atmIndex - 1] ?? null,
            OTM2: strikeList[atmIndex - 2] ?? null,
            OTM3: strikeList[atmIndex - 3] ?? null,
            OTM4: strikeList[atmIndex - 4] ?? null,
            OTM5: strikeList[atmIndex - 5] ?? null
        }
    };
}



async function scanSymbol(symbol, options = {}) {

    const {
        fromDate = null,
        toDate = null,
        mode = "intraday",
        expiry = null
    } = options;

    try {

        const expiries = expiry
            ? { [symbol]: expiry }
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
                    "x-device-id":
                        "83bc2e49-de14-45bc-91cb-ede7c156b16f",
                    "frt-ref":
                        Math.random()
                            .toString(36)
                            .substring(2)
                },
                body: JSON.stringify(requestPayload)
            }
        );

        const json = await response.json();

        if (!json.success || !json.payload) {

            return {
                symbol,
                error: "No data returned"
            };
        }

        const responseData = json.payload;

        const strikeMap =
            categorizeStrikes(
                responseData.atm_strike,
                responseData.strike_list
            );

        const perStrike =
            responseData.per_strike_data || {};

        const bucketData = {};

        // ATM

        const atmStrikeData =
            perStrike[strikeMap.ATM] || {};

        bucketData.ATM = {

            strike:
                strikeMap.ATM,

            callOiChange:
                atmStrikeData.call_oi_change ?? 0,

            putOiChange:
                atmStrikeData.put_oi_change ?? 0
        };

        // CE Buckets

        Object.entries(strikeMap.CE)
            .forEach(([bucket, strike]) => {

                if (!strike) return;

                const strikeData =
                    perStrike[strike] || {};

                bucketData[`CE_${bucket}`] = {

                    strike,

                    callOiChange:
                        strikeData.call_oi_change ?? 0
                };
            });

        // PE Buckets

        Object.entries(strikeMap.PE)
            .forEach(([bucket, strike]) => {

                if (!strike) return;

                const strikeData =
                    perStrike[strike] || {};

                bucketData[`PE_${bucket}`] = {

                    strike,

                    putOiChange:
                        strikeData.put_oi_change ?? 0
                };
            });

        // Research Fields

        bucketData.ITM_PE_Total =
            (bucketData.PE_ITM1?.putOiChange || 0) +
            (bucketData.PE_ITM2?.putOiChange || 0) +
            (bucketData.PE_ITM3?.putOiChange || 0);

        bucketData.OTM_PE_Total =
            (bucketData.PE_OTM1?.putOiChange || 0) +
            (bucketData.PE_OTM2?.putOiChange || 0) +
            (bucketData.PE_OTM3?.putOiChange || 0);

        bucketData.ITM_CE_Total =
            (bucketData.CE_ITM1?.callOiChange || 0) +
            (bucketData.CE_ITM2?.callOiChange || 0) +
            (bucketData.CE_ITM3?.callOiChange || 0);

        bucketData.OTM_CE_Total =
            (bucketData.CE_OTM1?.callOiChange || 0) +
            (bucketData.CE_OTM2?.callOiChange || 0) +
            (bucketData.CE_OTM3?.callOiChange || 0);

        bucketData.SupportMigration =
            bucketData.ITM_PE_Total -
            bucketData.OTM_PE_Total;

        bucketData.ResistanceMigration =
            bucketData.ITM_CE_Total -
            bucketData.OTM_CE_Total;

        console.log(
            symbol,
            responseData
        );

        return {

            symbol,

            spot:
                responseData.current_ltp,

            pcr:
                responseData.pcr,

            totalCallOI:
                responseData.total_call_oi_change,

            totalPutOI:
                responseData.total_put_oi_change,

            ...bucketData
        };

    } catch (err) {

        console.error(
            symbol,
            err
        );

        return {
            symbol,
            error:
                err.message
        };
    }
}

function downloadCSV(rows, options = {}) {

    const headers = [

        "Symbol",
        "Spot",
        "PCR",

        "ATM_Strike",
        "ATM_CallOI",
        "ATM_PutOI",

        "CE_ITM1_Strike", "CE_ITM1_CallOI",
        "CE_ITM2_Strike", "CE_ITM2_CallOI",
        "CE_ITM3_Strike", "CE_ITM3_CallOI",
        "CE_ITM4_Strike", "CE_ITM4_CallOI",
        "CE_ITM5_Strike", "CE_ITM5_CallOI",

        "CE_OTM1_Strike", "CE_OTM1_CallOI",
        "CE_OTM2_Strike", "CE_OTM2_CallOI",
        "CE_OTM3_Strike", "CE_OTM3_CallOI",
        "CE_OTM4_Strike", "CE_OTM4_CallOI",
        "CE_OTM5_Strike", "CE_OTM5_CallOI",

        "PE_ITM1_Strike", "PE_ITM1_PutOI",
        "PE_ITM2_Strike", "PE_ITM2_PutOI",
        "PE_ITM3_Strike", "PE_ITM3_PutOI",
        "PE_ITM4_Strike", "PE_ITM4_PutOI",
        "PE_ITM5_Strike", "PE_ITM5_PutOI",

        "PE_OTM1_Strike", "PE_OTM1_PutOI",
        "PE_OTM2_Strike", "PE_OTM2_PutOI",
        "PE_OTM3_Strike", "PE_OTM3_PutOI",
        "PE_OTM4_Strike", "PE_OTM4_PutOI",
        "PE_OTM5_Strike", "PE_OTM5_PutOI",

        "ITM_PE_Total",
        "ITM_CE_Total",
        "OTM_PE_Total",
        "OTM_CE_Total",

        "SupportMigration",
        "ResistanceMigration"
    ];

    const csvRows = rows.map(r => [

        r.symbol,
        r.spot,
        r.pcr,

        r.ATM?.strike,
        r.ATM?.callOiChange,
        r.ATM?.putOiChange,

        r.CE_ITM1?.strike,
        r.CE_ITM1?.callOiChange,

        r.CE_ITM2?.strike,
        r.CE_ITM2?.callOiChange,

        r.CE_ITM3?.strike,
        r.CE_ITM3?.callOiChange,

        r.CE_ITM4?.strike,
        r.CE_ITM4?.callOiChange,

        r.CE_ITM5?.strike,
        r.CE_ITM5?.callOiChange,

        r.CE_OTM1?.strike,
        r.CE_OTM1?.callOiChange,

        r.CE_OTM2?.strike,
        r.CE_OTM2?.callOiChange,

        r.CE_OTM3?.strike,
        r.CE_OTM3?.callOiChange,

        r.CE_OTM4?.strike,
        r.CE_OTM4?.callOiChange,

        r.CE_OTM5?.strike,
        r.CE_OTM5?.callOiChange,

        r.PE_ITM1?.strike,
        r.PE_ITM1?.putOiChange,

        r.PE_ITM2?.strike,
        r.PE_ITM2?.putOiChange,

        r.PE_ITM3?.strike,
        r.PE_ITM3?.putOiChange,

        r.PE_ITM4?.strike,
        r.PE_ITM4?.putOiChange,

        r.PE_ITM5?.strike,
        r.PE_ITM5?.putOiChange,

        r.PE_OTM1?.strike,
        r.PE_OTM1?.putOiChange,

        r.PE_OTM2?.strike,
        r.PE_OTM2?.putOiChange,

        r.PE_OTM3?.strike,
        r.PE_OTM3?.putOiChange,

        r.PE_OTM4?.strike,
        r.PE_OTM4?.putOiChange,

        r.PE_OTM5?.strike,
        r.PE_OTM5?.putOiChange,

        r.ITM_PE_Total,
        r.ITM_CE_Total,
        r.OTM_PE_Total,
        r.OTM_CE_Total,

        r.SupportMigration,
        r.ResistanceMigration

    ].join(","));

    const csv = [
        headers.join(","),
        ...csvRows
    ].join("\n");

    const blob = new Blob(
        [csv],
        {
            type: "text/csv"
        }
    );

    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");

    a.href = url;
    const now = new Date();
    const ts = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}-${String(now.getMinutes()).padStart(2, "0")}-${String(now.getSeconds()).padStart(2, "0")}`;

    let nameParts = ["sensibull_oi_scan"];

    if (options.fromDate) nameParts.push(options.fromDate);
    if (options.expiry) nameParts.push("exp_" + options.expiry);

    nameParts.push(ts);

    a.download = nameParts.join("_") + ".csv";

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

    const { fromDate, toDate } = options;

    // If a date range is provided, generate one file per date
    const dates =
        (fromDate && toDate)
            ? getDatesBetween(fromDate, toDate)
            : [null];

    let totalScanned = 0;

    for (const date of dates) {

        const dayOptions = { ...options };

        if (date) {
            dayOptions.fromDate = date;
            dayOptions.toDate = date;
        }

        const results = [];

        for (let i = 0; i < symbols.length; i++) {

            const symbol =
                symbols[i];

            console.log(
                `[${date || "today"}] Scanning ${i + 1}/${symbols.length}: ${symbol}`
            );

            const result =
                await scanSymbol(symbol, dayOptions);

            results.push(result);

            await new Promise(
                resolve =>
                    setTimeout(resolve, 1000)
            );
        }

        downloadCSV(results, dayOptions);

        totalScanned += results.length;
    }

    return totalScanned;
}

chrome.runtime.onMessage.addListener(
    (request, sender, sendResponse) => {

        console.log(
            "Received message:",
            request
        );

        if (
            request.action ===
            "runScan"
        ) {

            const options = {
                fromDate: request.fromDate || null,
                toDate: request.toDate || null,
                mode: request.mode || "intraday",
                expiry: request.expiry || null
            };

            runScanner(options)
                .then(count => {

                    sendResponse({
                        message:
                            `Completed ${count} symbols`
                    });

                })
                .catch(error => {

                    console.error(error);

                    sendResponse({
                        message:
                            error.message
                    });

                });

            return true;
        }
    }
);