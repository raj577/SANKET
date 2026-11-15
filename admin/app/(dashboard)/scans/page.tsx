"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Card,
  Empty,
  ErrorText,
  Field,
  Modal,
  Pagination,
  ProgressBar,
  Spinner
} from "@/components/ui";
import type { Tone } from "@/components/ui";
import { api, buildQuery } from "@/lib/api";
import { bytes, formatDateTime, num, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, PatternSymbolProgress, Scan, ScanDetail } from "@/lib/types";

const PAGE_SIZE = 25;

function toneForPattern(type: string): "green" | "red" | "amber" | "blue" | "gray" {
  switch (type) {
    case "AVWAP RECLAIM":
      return "green";
    case "AVWAP TOUCH":
      return "blue";
    case "AVWAP HUGGING":
      return "amber";
    default:
      return "gray";
  }
}

function toneForSymbolStatus(status: PatternSymbolProgress["status"]): Tone {
  switch (status) {
    case "MATCHED":
      return "green";
    case "ERROR":
      return "red";
    case "NO_DATA":
    case "SKIPPED":
      return "amber";
    case "SCANNING":
      return "blue";
    default:
      return "gray";
  }
}

function labelForSymbolStatus(status: PatternSymbolProgress["status"]): string {
  switch (status) {
    case "NO_PATTERN":
      return "no pattern";
    case "NO_DATA":
      return "no data";
    case "MATCHED":
      return "match";
    case "SCANNING":
      return "scanning";
    case "PENDING":
      return "queued";
    default:
      return status.toLowerCase();
  }
}

function timeframeLabel(timeframe: string | null): string {
  if (!timeframe) return "—";
  return timeframe === "D" ? "daily" : `${timeframe}m`;
}

/** Progress bar plus the per-instrument list recorded by the scan job. */
function PatternRunProgress({ detail }: { detail: ScanDetail }) {
  const progress = detail.pattern_progress;
  const symbols = detail.pattern_symbols;
  const running = detail.status === "PENDING" || detail.status === "RUNNING";
  const percent = progress?.percent ?? 0;
  const tone: Tone =
    detail.status === "FAILED"
      ? "red"
      : detail.status === "PARTIAL"
        ? "amber"
        : running
          ? "blue"
          : "green";

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div>
        <div className="progress-head">
          <strong>
            {running ? "Scanning" : "Scan finished"} ·{" "}
            {timeframeLabel(detail.timeframe)} candles
          </strong>
          <span className="muted">
            {progress ? `${progress.processed} / ${progress.total}` : "—"} · {percent}%
          </span>
        </div>
        <ProgressBar
          value={percent}
          tone={tone}
          label={`Pattern scan ${detail.id.slice(0, 8)} progress`}
        />
        <div className="progress-stats">
          <span className="pnl-pos">{progress?.matched ?? 0} matched</span>
          <span className="pnl-neg">{progress?.failed ?? 0} failed</span>
          <span>{progress?.pending ?? 0} pending</span>
          <span>{symbols.length} instrument(s) listed</span>
        </div>
      </div>

      {symbols.length > 0 ? (
        <div className="symbol-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Expiry</th>
                <th>Status</th>
                <th>Pattern</th>
                <th className="right">Candles</th>
                <th className="right">Last</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((entry) => (
                <tr key={`${entry.symbol}:${entry.expiry ?? ""}`}>
                  <td className="mono small">{entry.symbol}</td>
                  <td className="small muted">{entry.expiry ?? "—"}</td>
                  <td>
                    <Badge tone={toneForSymbolStatus(entry.status)}>
                      {labelForSymbolStatus(entry.status)}
                    </Badge>
                  </td>
                  <td>
                    {entry.pattern_type ? (
                      <Badge tone={toneForPattern(entry.pattern_type)}>
                        {entry.pattern_type}
                      </Badge>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="right">{entry.candles ?? "—"}</td>
                  <td className="right mono">
                    {entry.last_price ? num(entry.last_price) : "—"}
                  </td>
                  <td className="small muted">{entry.message ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty message="The instrument list appears once the scan resolves it." />
      )}
    </div>
  );
}

export default function ScansPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<ScanDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [symbols, setSymbols] = useState("");
  const [depth, setDepth] = useState(5);
  const [expiry, setExpiry] = useState("");
  const [starting, setStarting] = useState(false);
  const [startMessage, setStartMessage] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const [patternPage, setPatternPage] = useState(1);
  const [patternSymbols, setPatternSymbols] = useState("");
  const [patternTimeframe, setPatternTimeframe] = useState("60");
  const [patternStarting, setPatternStarting] = useState(false);
  const [patternMessage, setPatternMessage] = useState<string | null>(null);
  const [patternError, setPatternError] = useState<string | null>(null);
  const [patternDetail, setPatternDetail] = useState<ScanDetail | null>(null);
  const [patternDetailLoading, setPatternDetailLoading] = useState(false);
  const [patternDetailError, setPatternDetailError] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  // The most recent pattern run, polled for the progress bar and symbol list.
  const [activeScanId, setActiveScanId] = useState<string | null>(null);
  const [liveDetail, setLiveDetail] = useState<ScanDetail | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);

  const path = `/admin/scans${buildQuery({
    page,
    page_size: PAGE_SIZE,
    status,
    search,
    scan_type: "OI"
  })}`;
  const { data, loading, error, reload } = useApiData<Page<Scan>>(path);

  const patternPath = `/admin/scans${buildQuery({
    page: patternPage,
    page_size: PAGE_SIZE,
    scan_type: "AVWAP_PATTERN"
  })}`;
  const {
    data: patternData,
    loading: patternLoading,
    error: patternListError,
    reload: reloadPattern
  } = useApiData<Page<Scan>>(patternPath);

  useEffect(() => {
    const running = data?.items.some(
      (scan) => scan.status === "PENDING" || scan.status === "RUNNING"
    );
    if (!running) return;
    const timer = window.setInterval(reload, 4000);
    return () => window.clearInterval(timer);
  }, [data, reload]);

  useEffect(() => {
    const running = patternData?.items.some(
      (scan) => scan.status === "PENDING" || scan.status === "RUNNING"
    );
    if (!running) return;
    const timer = window.setInterval(reloadPattern, 4000);
    return () => window.clearInterval(timer);
  }, [patternData, reloadPattern]);

  // Adopt a pattern scan that is already running (for example after a reload),
  // so the progress bar reappears without re-queuing anything.
  useEffect(() => {
    if (activeScanId) return;
    const running = patternData?.items.find(
      (scan) => scan.status === "PENDING" || scan.status === "RUNNING"
    );
    if (running) setActiveScanId(running.id);
  }, [patternData, activeScanId]);

  const loadLiveScan = useCallback(
    async (scanId: string) => {
      try {
        const value = await api.get<ScanDetail>(`/admin/scans/${scanId}`);
        setLiveDetail(value);
        setLiveError(null);
        if (value.status !== "PENDING" && value.status !== "RUNNING") {
          reloadPattern();
        }
      } catch (err) {
        setLiveError(
          err instanceof Error ? err.message : "Unable to load scan progress"
        );
      }
    },
    [reloadPattern]
  );

  const liveRunning =
    liveDetail?.status === "PENDING" || liveDetail?.status === "RUNNING";

  useEffect(() => {
    if (!activeScanId) return;
    void loadLiveScan(activeScanId);
  }, [activeScanId, loadLiveScan]);

  useEffect(() => {
    if (!activeScanId || !liveRunning) return;
    const timer = window.setInterval(() => {
      void loadLiveScan(activeScanId);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeScanId, liveRunning, loadLiveScan]);

  async function runOiScan() {
    setStarting(true);
    setStartError(null);
    setStartMessage(null);
    const parsed = symbols
      .split(/[\s,]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    try {
      const scan = await api.post<Scan>("/admin/scans/oi", {
        symbols: parsed.length ? parsed : null,
        depth,
        expiry: expiry || null
      });
      setStartMessage(`Scan ${scan.id.slice(0, 8)} queued. Candidates appear when it finishes.`);
      setPage(1);
      reload();
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "Unable to start the OI scan");
    } finally {
      setStarting(false);
    }
  }

  async function openDetail(scanId: string) {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const value = await api.get<ScanDetail>(`/admin/scans/${scanId}`);
      setDetail(value);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Unable to load scan");
    } finally {
      setDetailLoading(false);
    }
  }

  async function download(scan: Scan) {
    setActionError(null);
    try {
      await api.download(
        `/admin/archives/${scan.id}/download`,
        scan.csv_filename || `scan-${scan.id}.csv`
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function runPatternScan() {
    setPatternStarting(true);
    setPatternError(null);
    setPatternMessage(null);
    const parsed = patternSymbols
      .split(/[\s,]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    try {
      const scan = await api.post<Scan>("/admin/scans/pattern", {
        symbols: parsed.length ? parsed : null,
        timeframe: patternTimeframe
      });
      setPatternMessage(
        `Pattern scan ${scan.id.slice(0, 8)} queued for ${patternTimeframe === "D" ? "daily" : `${patternTimeframe}m`} candles. Results appear when it finishes.`
      );
      setPatternPage(1);
      setActiveScanId(scan.id);
      setLiveDetail(null);
      setLiveError(null);
      reloadPattern();
    } catch (err) {
      setPatternError(
        err instanceof Error ? err.message : "Unable to start the pattern scan"
      );
    } finally {
      setPatternStarting(false);
    }
  }

  async function openPatternDetail(scanId: string) {
    setPatternDetailLoading(true);
    setPatternDetailError(null);
    try {
      const value = await api.get<ScanDetail>(`/admin/scans/${scanId}`);
      setPatternDetail(value);
    } catch (err) {
      setPatternDetailError(
        err instanceof Error ? err.message : "Unable to load pattern scan"
      );
    } finally {
      setPatternDetailLoading(false);
    }
  }

  async function reviewPatternCandidate(
    candidateId: string,
    action: "approve" | "reject"
  ) {
    setReviewingId(candidateId);
    setPatternError(null);
    try {
      await api.post(
        `/admin/pattern-candidates/${candidateId}/${action}`,
        action === "reject" ? { reason: null } : {}
      );
      if (patternDetail) {
        const value = await api.get<ScanDetail>(`/admin/scans/${patternDetail.id}`);
        setPatternDetail(value);
      }
      reloadPattern();
    } catch (err) {
      setPatternError(
        err instanceof Error ? err.message : "Unable to update the candidate"
      );
    } finally {
      setReviewingId(null);
    }
  }

  return (
    <>
      <Card
        title="Run OI scan"
        actions={<Badge tone="blue">No extension</Badge>}
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field label="Symbols" hint="Comma or newline separated. Blank uses the saved watchlist.">
            <textarea
              value={symbols}
              onChange={(event) => setSymbols(event.target.value)}
              placeholder="NIFTY, RELIANCE, WIPRO"
              rows={3}
              style={{ minWidth: 320 }}
            />
          </Field>
          <Field label="Strike depth">
            <input
              type="number"
              min={3}
              max={10}
              value={depth}
              onChange={(event) => setDepth(Math.max(3, Math.min(10, Number(event.target.value) || 5)))}
            />
          </Field>
          <Field label="Expiry" hint="Optional, YYYY-MM-DD">
            <input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
          </Field>
          <div className="flex" style={{ alignItems: "flex-end" }}>
            <button className="btn" onClick={runOiScan} disabled={starting}>
              {starting ? "Starting…" : "Run OI scan"}
            </button>
          </div>
        </div>
        {startMessage ? <div className="success-text">{startMessage}</div> : null}
        <ErrorText error={startError} />
        <div className="muted small">
          Fetches FYERS option-chain OI changes and runs the same versioned filter. The
          generated CSV is archived like an extension upload. FYERS must be connected
          under Settings first.
        </div>
      </Card>

      <Card
        title="AVWAP / Pattern Scanner"
        actions={<Badge tone="blue">Independent scanner</Badge>}
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field
            label="Symbols"
            hint="Full FYERS futures symbols or underlyings. Blank scans the current-expiry futures universe."
          >
            <textarea
              value={patternSymbols}
              onChange={(event) => setPatternSymbols(event.target.value)}
              placeholder="NSE:NIFTY25NOVFUT, NSE:BANKNIFTY25NOVFUT"
              rows={3}
              style={{ minWidth: 320 }}
            />
          </Field>
          <Field label="Timeframe">
            <select
              value={patternTimeframe}
              onChange={(event) => setPatternTimeframe(event.target.value)}
            >
              <option value="5">5 minutes</option>
              <option value="15">15 minutes</option>
              <option value="60">60 minutes</option>
              <option value="D">Daily</option>
            </select>
          </Field>
          <div className="flex" style={{ alignItems: "flex-end" }}>
            <button className="btn" onClick={runPatternScan} disabled={patternStarting}>
              {patternStarting ? "Starting…" : "Run pattern scan"}
            </button>
          </div>
        </div>
        {patternMessage ? <div className="success-text">{patternMessage}</div> : null}
        <ErrorText error={patternError} />
        <ErrorText error={liveError} />

        {liveDetail ? (
          <div style={{ marginTop: 16 }}>
            <div
              className="flex"
              style={{ justifyContent: "space-between", marginBottom: 10 }}
            >
              <span className="section-title" style={{ margin: 0 }}>
                Live progress
              </span>
              <span className="muted small mono">
                {liveDetail.id.slice(0, 8)}
              </span>
            </div>
            <PatternRunProgress detail={liveDetail} />
          </div>
        ) : activeScanId ? (
          <div style={{ marginTop: 16 }}>
            <Spinner label="Loading scan progress" />
          </div>
        ) : null}

        <div className="muted small" style={{ marginTop: 14 }}>
          Detects the original contract-start AVWAP patterns — TOUCH, HUGGING,
          CONSOLIDATION and RECLAIM — from completed FYERS candles only. This scanner is
          independent of the OI scanner and its scoring.
        </div>
      </Card>

      <Card
        title="Scan runs"
        actions={
          <button className="btn ghost small" onClick={reload}>
            Refresh
          </button>
        }
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field label="Status">
            <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
              <option value="">All statuses</option>
              {["PENDING", "RUNNING", "COMPLETED", "PARTIAL", "FAILED"].map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </Field>
          <Field label="CSV filename" hint="Literal substring">
            <input
              value={search}
              placeholder="sensibull_oi_scan_..."
              onChange={(event) => { setSearch(event.target.value); setPage(1); }}
            />
          </Field>
          <div className="spacer" />
        </div>

        <ErrorText error={error || actionError} />

        {loading && !data ? (
          <Spinner label="Loading scans" />
        ) : data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Started (IST)</th>
                    <th>Status</th>
                    <th className="right">Symbols</th>
                    <th className="right">LONG</th>
                    <th className="right">SHORT</th>
                    <th>CSV archive</th>
                    <th>Trigger</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((scan) => (
                    <tr key={scan.id}>
                      <td className="nowrap">
                        <div>{formatDateTime(scan.started_at)}</div>
                        <span className="muted small mono">{scan.id.slice(0, 8)}</span>
                      </td>
                      <td><Badge tone={toneForStatus(scan.status)}>{scan.status}</Badge></td>
                      <td className="right nowrap">
                        {scan.successful_symbols}/{scan.total_symbols}
                        {scan.failed_symbols > 0 ? (
                          <div className="muted small">{scan.failed_symbols} failed</div>
                        ) : null}
                      </td>
                      <td className="right">{scan.long_candidates_count}</td>
                      <td className="right">{scan.short_candidates_count}</td>
                      <td>
                        {scan.csv_filename ? (
                          <>
                            <div className="mono small">{scan.csv_filename}</div>
                            <span className="muted small">{bytes(scan.csv_size_bytes)}</span>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="muted small">{scan.trigger || "—"}</td>
                      <td className="nowrap">
                        <div className="flex">
                          <button className="btn ghost small" onClick={() => openDetail(scan.id)}>
                            Detail
                          </button>
                          {scan.csv_storage_path ? (
                            <button className="btn ghost small" onClick={() => download(scan)}>
                              CSV
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <Empty message="No scans match these filters." />
        )}
      </Card>

      <Card
        title="Pattern scan runs"
        actions={
          <button className="btn ghost small" onClick={reloadPattern}>
            Refresh
          </button>
        }
      >
        <ErrorText error={patternListError || patternError} />
        {patternLoading && !patternData ? (
          <Spinner label="Loading pattern scans" />
        ) : patternData && patternData.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Started (IST)</th>
                    <th>Status</th>
                    <th>Timeframe</th>
                    <th className="right">Instruments</th>
                    <th>Trigger</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {patternData.items.map((scan) => (
                    <tr key={scan.id}>
                      <td className="nowrap">
                        <div>{formatDateTime(scan.started_at)}</div>
                        <span className="muted small mono">{scan.id.slice(0, 8)}</span>
                      </td>
                      <td>
                        <Badge tone={toneForStatus(scan.status)}>{scan.status}</Badge>
                      </td>
                      <td>{scan.timeframe || "—"}</td>
                      <td className="right nowrap">
                        {scan.successful_symbols}/{scan.total_symbols}
                        {scan.failed_symbols > 0 ? (
                          <div className="muted small">{scan.failed_symbols} failed</div>
                        ) : null}
                      </td>
                      <td className="muted small">{scan.trigger || "—"}</td>
                      <td className="nowrap">
                        <button
                          className="btn ghost small"
                          onClick={() => openPatternDetail(scan.id)}
                        >
                          Detail
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={patternPage}
              pageSize={PAGE_SIZE}
              total={patternData.total}
              onChange={setPatternPage}
            />
          </>
        ) : (
          <Empty message="No pattern scans yet." />
        )}
      </Card>

      <Modal
        open={Boolean(detail) || detailLoading || Boolean(detailError)}
        title={detail ? `Scan ${detail.id.slice(0, 8)}` : "Scan detail"}
        onClose={() => { setDetail(null); setDetailError(null); }}
        wide
      >
        {detailLoading ? <Spinner label="Loading scan" /> : null}
        <ErrorText error={detailError} />
        {detail ? (
          <div style={{ display: "grid", gap: 16 }}>
            <dl className="kv">
              <dt>Status</dt>
              <dd><Badge tone={toneForStatus(detail.status)}>{detail.status}</Badge></dd>
              <dt>Started</dt>
              <dd>{formatDateTime(detail.started_at)}</dd>
              <dt>Completed</dt>
              <dd>{formatDateTime(detail.completed_at)}</dd>
              <dt>Symbols</dt>
              <dd>{detail.successful_symbols} successful · {detail.failed_symbols} failed · {detail.total_symbols} total</dd>
              <dt>Last progress</dt>
              <dd>{detail.last_progress_symbol || "—"}</dd>
              <dt>Scanner version</dt>
              <dd className="mono">{detail.scanner_version || "—"}</dd>
              <dt>CSV file</dt>
              <dd className="mono small">{detail.csv_filename || "—"}</dd>
              <dt>SHA-256</dt>
              <dd className="mono small" style={{ wordBreak: "break-all" }}>{detail.csv_checksum_sha256 || "—"}</dd>
              <dt>Error / warnings</dt>
              <dd>{detail.error_message || (detail.warnings.length ? detail.warnings.join("; ") : "—")}</dd>
            </dl>
            {detail.scanner_config ? (
              <div>
                <div className="section-title">Scanner configuration</div>
                <pre className="code-block">{JSON.stringify(detail.scanner_config, null, 2)}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={
          Boolean(patternDetail) ||
          patternDetailLoading ||
          Boolean(patternDetailError)
        }
        title={
          patternDetail
            ? `Pattern scan ${patternDetail.id.slice(0, 8)}`
            : "Pattern scan detail"
        }
        onClose={() => {
          setPatternDetail(null);
          setPatternDetailError(null);
        }}
        wide
      >
        {patternDetailLoading ? <Spinner label="Loading pattern scan" /> : null}
        <ErrorText error={patternDetailError} />
        {patternDetail ? (
          <div style={{ display: "grid", gap: 16 }}>
            <dl className="kv">
              <dt>Status</dt>
              <dd>
                <Badge tone={toneForStatus(patternDetail.status)}>
                  {patternDetail.status}
                </Badge>
              </dd>
              <dt>Timeframe</dt>
              <dd>
                {patternDetail.timeframe === "D"
                  ? "Daily"
                  : patternDetail.timeframe
                    ? `${patternDetail.timeframe} minutes`
                    : "—"}
              </dd>
              <dt>Started</dt>
              <dd>{formatDateTime(patternDetail.started_at)}</dd>
              <dt>Completed</dt>
              <dd>{formatDateTime(patternDetail.completed_at)}</dd>
              <dt>Instruments</dt>
              <dd>
                {patternDetail.successful_symbols} scanned ·{" "}
                {patternDetail.failed_symbols} failed ·{" "}
                {patternDetail.total_symbols} total
              </dd>
              <dt>Scanner version</dt>
              <dd className="mono">{patternDetail.scanner_version || "—"}</dd>
              <dt>Detections</dt>
              <dd>
                {patternDetail.pattern_summary
                  ? `${patternDetail.pattern_summary.matches} match(es) across ${patternDetail.pattern_summary.instruments_resolved} instrument(s)`
                  : "—"}
              </dd>
              <dt>Errors</dt>
              <dd>
                {patternDetail.error_message ||
                  (patternDetail.warnings.length
                    ? patternDetail.warnings.join("; ")
                    : "—")}
              </dd>
            </dl>

            <div>
              <div className="section-title">Progress and symbols</div>
              <PatternRunProgress detail={patternDetail} />
            </div>

            {patternDetail.pattern_summary ? (
              <div>
                <div className="section-title">Classification counts</div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Classification</th>
                        <th className="right">Detections</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        patternDetail.pattern_summary.classification_counts
                      ).map(([label, count]) => (
                        <tr key={label}>
                          <td>
                            <Badge tone={toneForPattern(label)}>{label}</Badge>
                          </td>
                          <td className="right">{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            <div>
              <div className="section-title">Detected patterns</div>
              {patternDetail.pattern_candidates.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Instrument</th>
                        <th>Classification</th>
                        <th className="right">Candles</th>
                        <th className="right">Last</th>
                        <th className="right">AVWAP</th>
                        <th className="right">Distance</th>
                        <th className="right">ATR</th>
                        <th>Detected (IST)</th>
                        <th>Status</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {patternDetail.pattern_candidates.map((candidate) => (
                        <tr key={candidate.id}>
                          <td>
                            <div className="mono small">{candidate.symbol}</div>
                            <div className="muted small">
                              {candidate.expiry || "—"}
                            </div>
                          </td>
                          <td>
                            <Badge tone={toneForPattern(candidate.pattern_type)}>
                              {candidate.pattern_type}
                            </Badge>
                          </td>
                          <td className="right">{candidate.candle_count}</td>
                          <td className="right mono">{num(candidate.last_price)}</td>
                          <td className="right mono">{num(candidate.avwap)}</td>
                          <td className="right mono">
                            {Number(candidate.distance_pct) > 0 ? "+" : ""}
                            {num(candidate.distance_pct, 3)}%
                          </td>
                          <td className="right mono">{num(candidate.atr)}</td>
                          <td className="small">
                            {formatDateTime(candidate.pattern_end)}
                          </td>
                          <td>
                            <Badge tone={toneForStatus(candidate.status)}>
                              {candidate.status}
                            </Badge>
                          </td>
                          <td className="nowrap">
                            <button
                              className="btn ghost small"
                              disabled={
                                reviewingId === candidate.id ||
                                candidate.status === "PUBLISHED" ||
                                candidate.status === "EXPIRED"
                              }
                              onClick={() =>
                                reviewPatternCandidate(candidate.id, "approve")
                              }
                            >
                              {reviewingId === candidate.id ? "…" : "Approve"}
                            </button>
                            <button
                              className="btn ghost small"
                              disabled={
                                reviewingId === candidate.id ||
                                candidate.status === "PUBLISHED" ||
                                candidate.status === "REJECTED"
                              }
                              onClick={() =>
                                reviewPatternCandidate(candidate.id, "reject")
                              }
                            >
                              Reject
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty message="No patterns were detected in this run." />
              )}
            </div>

            {patternDetail.pattern_config ? (
              <div>
                <div className="section-title">Detector configuration</div>
                <pre className="code-block">
                  {JSON.stringify(patternDetail.pattern_config, null, 2)}
                </pre>
              </div>
            ) : null}

            {patternDetail.scanner_config ? (
              <div>
                <div className="section-title">Execution metadata</div>
                <pre className="code-block">
                  {JSON.stringify(patternDetail.scanner_config, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </>
  );
}
