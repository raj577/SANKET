"use client";

import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Modal, Pagination, Spinner } from "@/components/ui";
import { api, buildQuery } from "@/lib/api";
import { bytes, formatDateTime, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, Scan, ScanDetail } from "@/lib/types";

const PAGE_SIZE = 25;

export default function ScansPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<ScanDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const path = `/admin/scans${buildQuery({ page, page_size: PAGE_SIZE, status, search })}`;
  const { data, loading, error, reload } = useApiData<Page<Scan>>(path);

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

  return (
    <>
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
    </>
  );
}
