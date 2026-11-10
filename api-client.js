/**
 * Minimal backend client used by the extension service worker.
 *
 * The collector token is kept in chrome.storage.local and only sent to the
 * configured backend origin. Uploads happen from the service worker so the
 * https Sensibull page is never asked to call a plain-http backend.
 */
(function (global) {
    "use strict";

    const API_PREFIX = "/api/v1";

    class SensibullApiError extends Error {
        constructor(message, status, code) {
            super(message);
            this.name = "SensibullApiError";
            this.status = status || 0;
            this.code = code || "api_error";
        }
    }

    function normalizeBaseUrl(value) {
        const raw = String(value || "").trim();
        if (!raw) throw new SensibullApiError("Backend URL is not configured");
        let url;
        try {
            url = new URL(raw);
        } catch (error) {
            throw new SensibullApiError("Backend URL is not a valid URL");
        }
        if (!/^https?:$/.test(url.protocol)) {
            throw new SensibullApiError("Backend URL must start with http:// or https://");
        }
        let path = url.pathname.replace(/\/+$/, "");
        if (path.endsWith("/api/v1")) path = path.slice(0, -"/api/v1".length);
        return url.origin + path;
    }

    function extractErrorMessage(payload, fallback) {
        if (!payload) return fallback;
        if (typeof payload.detail === "string") return payload.detail;
        if (Array.isArray(payload.detail)) {
            return payload.detail
                .map((item) => (item && item.msg ? item.msg : JSON.stringify(item)))
                .join("; ");
        }
        if (typeof payload.message === "string") return payload.message;
        return fallback;
    }

    class SensibullApi {
        constructor(config) {
            const cfg = config || {};
            this.baseUrl = normalizeBaseUrl(cfg.baseUrl);
            this.token = String(cfg.collectorToken || "").trim();
            if (!this.token) throw new SensibullApiError("Collector token is not configured");
        }

        async request(path, options) {
            const opts = options || {};
            const controller = new AbortController();
            const timeoutMs = opts.timeoutMs || 20000;
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            const headers = Object.assign(
                { Accept: "application/json", "X-Collector-Token": this.token },
                opts.headers || {}
            );
            try {
                const response = await fetch(this.baseUrl + API_PREFIX + path, {
                    method: opts.method || "GET",
                    headers,
                    body: opts.body,
                    signal: controller.signal
                });
                const text = await response.text();
                let payload = null;
                if (text) {
                    try {
                        payload = JSON.parse(text);
                    } catch (error) {
                        payload = null;
                    }
                }
                if (!response.ok) {
                    throw new SensibullApiError(
                        extractErrorMessage(payload, `Backend returned HTTP ${response.status}`),
                        response.status,
                        payload && payload.code
                    );
                }
                return payload || {};
            } catch (error) {
                if (error instanceof SensibullApiError) throw error;
                if (error && error.name === "AbortError") {
                    throw new SensibullApiError("Backend request timed out");
                }
                throw new SensibullApiError("Cannot reach the backend: " + (error?.message || "network error"));
            } finally {
                clearTimeout(timer);
            }
        }

        health() {
            return this.requestHealth();
        }

        async requestHealth() {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 10000);
            try {
                const response = await fetch(this.baseUrl + "/health", { signal: controller.signal });
                if (!response.ok) throw new SensibullApiError(`Backend health check failed (${response.status})`);
                return await response.json();
            } catch (error) {
                if (error instanceof SensibullApiError) throw error;
                if (error && error.name === "AbortError") {
                    throw new SensibullApiError("Backend health check timed out");
                }
                throw new SensibullApiError("Cannot reach the backend: " + (error?.message || "network error"));
            } finally {
                clearTimeout(timer);
            }
        }

        createScan(scanId, totalSymbols, startedAt, trigger) {
            return this.request("/collector/scans", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    scan_id: scanId,
                    started_at: startedAt,
                    total_symbols: totalSymbols || 0,
                    trigger: trigger || "extension"
                })
            });
        }

        reportProgress(scanId, data) {
            return this.request(`/collector/scans/${encodeURIComponent(scanId)}/progress`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data || {}),
                timeoutMs: 10000
            });
        }

        uploadCsv(scanId, csvText, meta) {
            const info = meta || {};
            const form = new FormData();
            const blob = new Blob([csvText], { type: "text/csv" });
            form.append("file", blob, info.filename || "sensibull_oi_scan.csv");
            if (info.total !== undefined && info.total !== null) form.append("total_symbols", String(info.total));
            if (info.successful !== undefined && info.successful !== null) {
                form.append("successful_symbols", String(info.successful));
            }
            if (info.failed !== undefined && info.failed !== null) form.append("failed_symbols", String(info.failed));
            return this.request(`/collector/scans/${encodeURIComponent(scanId)}/csv`, {
                method: "POST",
                body: form,
                timeoutMs: 120000
            });
        }

        completeScan(scanId, data) {
            return this.request(`/collector/scans/${encodeURIComponent(scanId)}/complete`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data || {}),
                timeoutMs: 20000
            });
        }

        getStatus() {
            return this.request("/collector/status", { timeoutMs: 10000 });
        }

        async testConnection() {
            await this.requestHealth();
            return this.getStatus();
        }
    }

    global.SensibullApi = SensibullApi;
    global.SensibullApiError = SensibullApiError;
    if (typeof module !== "undefined" && module.exports) {
        module.exports = { SensibullApi, SensibullApiError };
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
