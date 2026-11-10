/**
 * Manual integration check for the extension -> backend upload path.
 *
 * Usage:
 *   set API_BASE=http://127.0.0.1:8000
 *   set COLLECTOR_TOKEN=col_...
 *   node extension-tests/backend-e2e.js
 */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const Csv = require("../csv-utils.js");
const { SensibullApi } = require("../api-client.js");

const baseUrl = process.env.API_BASE || "http://127.0.0.1:8000";
const collectorToken = process.env.COLLECTOR_TOKEN;
if (!collectorToken) {
    console.error("Set COLLECTOR_TOKEN to a valid collector token.");
    process.exit(2);
}

const samplePath = path.join(__dirname, "..", "sensibull_oi_scan_2026-11-09_12-26.csv");
const lines = fs.readFileSync(samplePath, "utf8").trim().split(/\r?\n/);
const headers = lines[0].split(",");
const DEPTH = 5;

function toNumber(value) {
    if (value === "" || value === undefined) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function parseRow(line) {
    const cells = line.split(",");
    const raw = {};
    headers.forEach((header, index) => {
        raw[header] = cells[index];
    });

    const row = {
        symbol: raw.Symbol,
        spot: toNumber(raw.Spot),
        pcr: toNumber(raw.PCR),
        depth: DEPTH,
        ATM: {
            strike: toNumber(raw.ATM_Strike),
            callOiChange: toNumber(raw.ATM_CallOI),
            putOiChange: toNumber(raw.ATM_PutOI)
        },
        ITM_PE_Total: toNumber(raw.ITM_PE_Total),
        ITM_CE_Total: toNumber(raw.ITM_CE_Total),
        OTM_PE_Total: toNumber(raw.OTM_PE_Total),
        OTM_CE_Total: toNumber(raw.OTM_CE_Total),
        SupportMigration: toNumber(raw.SupportMigration),
        ResistanceMigration: toNumber(raw.ResistanceMigration)
    };

    for (let i = 1; i <= DEPTH; i++) {
        row[`CE_ITM${i}`] = {
            strike: toNumber(raw[`CE_ITM${i}_Strike`]),
            callOiChange: toNumber(raw[`CE_ITM${i}_CallOI`])
        };
        row[`CE_OTM${i}`] = {
            strike: toNumber(raw[`CE_OTM${i}_Strike`]),
            callOiChange: toNumber(raw[`CE_OTM${i}_CallOI`])
        };
        row[`PE_ITM${i}`] = {
            strike: toNumber(raw[`PE_ITM${i}_Strike`]),
            putOiChange: toNumber(raw[`PE_ITM${i}_PutOI`])
        };
        row[`PE_OTM${i}`] = {
            strike: toNumber(raw[`PE_OTM${i}_Strike`]),
            putOiChange: toNumber(raw[`PE_OTM${i}_PutOI`])
        };
    }
    return row;
}

async function main() {
    const rows = lines.slice(1).map(parseRow);
    assert.equal(rows.length, 213);
    const csvText = Csv.buildCSV(rows, { depth: DEPTH });
    const summary = Csv.summarize(rows);
    assert.equal(summary.successful, rows.length);

    const api = new SensibullApi({ baseUrl, collectorToken });
    await api.health();
    const scanId = crypto.randomUUID();
    await api.createScan(scanId, rows.length, new Date().toISOString(), "extension-e2e");
    const uploaded = await api.uploadCsv(scanId, csvText, {
        filename: Csv.buildFileName({ depth: DEPTH }),
        total: summary.total,
        successful: summary.successful,
        failed: summary.failed
    });
    assert.equal(uploaded.status, "COMPLETED", JSON.stringify(uploaded));
    assert.equal(uploaded.long_candidates_count, 8);
    assert.equal(uploaded.short_candidates_count, 7);
    const completed = await api.completeScan(scanId, {
        status: uploaded.status,
        successful_symbols: summary.successful,
        failed_symbols: summary.failed
    });
    assert.equal(completed.status, "COMPLETED");
    const status = await api.getStatus();
    assert.equal(status.storage_backend, "local");
    console.log("extension backend e2e passed", {
        scanId,
        csv: uploaded.csv_filename,
        longs: uploaded.long_candidates_count,
        shorts: uploaded.short_candidates_count
    });
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
