const assert = require("node:assert/strict");

const Csv = require("../csv-utils.js");
const { SensibullApi, SensibullApiError } = require("../api-client.js");

const row = {
    symbol: "WIPRO",
    spot: 250.5,
    pcr: 1.23,
    depth: 5,
    ATM: { strike: 250, callOiChange: -100, putOiChange: 200 },
    CE_ITM1: { strike: 245, callOiChange: 10 },
    CE_ITM2: { strike: 240, callOiChange: 20 },
    CE_ITM3: { strike: 235, callOiChange: 0 },
    CE_ITM4: { strike: 230, callOiChange: 5 },
    CE_ITM5: { strike: 225, callOiChange: 6 },
    CE_OTM1: { strike: 255, callOiChange: -10 },
    PE_ITM1: { strike: 255, putOiChange: 11 },
    PE_OTM1: { strike: 245, putOiChange: -11 },
    ITM_PE_Total: 100,
    ITM_CE_Total: 50,
    OTM_PE_Total: 25,
    OTM_CE_Total: -5,
    SupportMigration: 75,
    ResistanceMigration: 55
};

const csv = Csv.buildCSV([row], { depth: 5 });
const lines = csv.split("\n");
assert.equal(lines.length, 2);
assert.ok(lines[0].startsWith("Symbol,Spot,PCR,ATM_Strike,ATM_CallOI,ATM_PutOI,CE_ITM1_Strike,CE_ITM1_CallOI"));
assert.ok(lines[0].includes("ResistanceMigration"));
assert.equal(lines[1].split(",")[0], "WIPRO");
assert.equal(lines[1].split(",")[1], "250.5");

const filename = Csv.buildFileName(
    { fromDate: "2026-11-09", expiry: "2026-11-13" },
    new Date(2026, 10, 9, 12, 26, 0)
);
assert.equal(filename, "sensibull_oi_scan_2026-11-09_exp_2026-11-13_2026-11-09_12-26.csv");

assert.deepEqual(Csv.summarize([{ symbol: "A" }, { symbol: "B", error: "x" }]), {
    total: 2,
    successful: 1,
    failed: 1
});

const escaped = Csv.buildCSV([{ symbol: 'A,"B"', spot: 1, depth: 5 }], { depth: 5 });
assert.ok(escaped.split("\n")[1].startsWith('"A,""B"""'));

const api = new SensibullApi({ baseUrl: "http://localhost:8000/api/v1/", collectorToken: "token" });
assert.equal(api.baseUrl, "http://localhost:8000");
assert.throws(
    () => new SensibullApi({ baseUrl: "http://localhost:8000", collectorToken: "" }),
    SensibullApiError
);
assert.throws(
    () => new SensibullApi({ baseUrl: "ftp://localhost", collectorToken: "token" }),
    SensibullApiError
);

console.log("extension unit tests passed");
