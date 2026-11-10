/**
 * Shared CSV builder for the Sensibull scanner.
 *
 * Loaded by the content script (manifest) and the service worker (importScripts)
 * so the exact same columns, ordering and values are used for local downloads
 * and backend uploads.
 */
(function (global) {
    "use strict";

    function buildHeaders(depth) {
        const headers = ["Symbol", "Spot", "PCR", "ATM_Strike", "ATM_CallOI", "ATM_PutOI"];
        for (let i = 1; i <= depth; i++) headers.push(`CE_ITM${i}_Strike`, `CE_ITM${i}_CallOI`);
        for (let i = 1; i <= depth; i++) headers.push(`CE_OTM${i}_Strike`, `CE_OTM${i}_CallOI`);
        for (let i = 1; i <= depth; i++) headers.push(`PE_ITM${i}_Strike`, `PE_ITM${i}_PutOI`);
        for (let i = 1; i <= depth; i++) headers.push(`PE_OTM${i}_Strike`, `PE_OTM${i}_PutOI`);
        headers.push(
            "ITM_PE_Total",
            "ITM_CE_Total",
            "OTM_PE_Total",
            "OTM_CE_Total",
            "SupportMigration",
            "ResistanceMigration"
        );
        return headers;
    }

    function cellValue(value) {
        if (value === null || value === undefined) return "";
        return String(value);
    }

    function escapeCell(value) {
        const text = cellValue(value);
        if (/[",\r\n]/.test(text)) {
            return '"' + text.replace(/"/g, '""') + '"';
        }
        return text;
    }

    function resolveDepth(rows, options) {
        const requested = Number(options.depth);
        if (Number.isFinite(requested) && requested > 0) return Math.floor(requested);
        const fromRows = rows.map((row) => Number(row && row.depth) || 5);
        return Math.max(5, ...fromRows);
    }

    function buildRow(row, depth) {
        const values = [row.symbol, row.spot, row.pcr, row.ATM?.strike, row.ATM?.callOiChange, row.ATM?.putOiChange];
        for (let i = 1; i <= depth; i++) {
            values.push(row[`CE_ITM${i}`]?.strike, row[`CE_ITM${i}`]?.callOiChange);
        }
        for (let i = 1; i <= depth; i++) {
            values.push(row[`CE_OTM${i}`]?.strike, row[`CE_OTM${i}`]?.callOiChange);
        }
        for (let i = 1; i <= depth; i++) {
            values.push(row[`PE_ITM${i}`]?.strike, row[`PE_ITM${i}`]?.putOiChange);
        }
        for (let i = 1; i <= depth; i++) {
            values.push(row[`PE_OTM${i}`]?.strike, row[`PE_OTM${i}`]?.putOiChange);
        }
        values.push(
            row.ITM_PE_Total,
            row.ITM_CE_Total,
            row.OTM_PE_Total,
            row.OTM_CE_Total,
            row.SupportMigration,
            row.ResistanceMigration
        );
        return values.map(escapeCell).join(",");
    }

    function buildCSV(rows, options) {
        const list = Array.isArray(rows) ? rows : [];
        const depth = resolveDepth(list, options || {});
        const headers = buildHeaders(depth);
        const lines = [headers.join(",")];
        for (const row of list) {
            lines.push(buildRow(row || {}, depth));
        }
        return lines.join("\n");
    }

    function pad2(value) {
        return String(value).padStart(2, "0");
    }

    function buildFileName(options, now) {
        const opts = options || {};
        const date = now instanceof Date ? now : new Date();
        const ts = `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}_${pad2(date.getHours())}-${pad2(date.getMinutes())}`;
        const parts = ["sensibull_oi_scan"];
        if (opts.fromDate) parts.push(opts.fromDate);
        if (opts.expiry) parts.push("exp_" + opts.expiry);
        parts.push(ts);
        return parts.join("_") + ".csv";
    }

    function summarize(rows) {
        const list = Array.isArray(rows) ? rows : [];
        const successful = list.filter((row) => !row?.error).length;
        return { total: list.length, successful, failed: list.length - successful };
    }

    const api = { buildHeaders, buildCSV, buildFileName, summarize };
    global.SensibullCsv = api;
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
