"use client";

import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Modal, Pagination, Spinner } from "@/components/ui";
import { api, buildQuery } from "@/lib/api";
import { formatDateTime, num, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Candidate, Page, Scan, Signal } from "@/lib/types";

const PAGE_SIZE = 25;

export default function CandidatesPage() {
  const [scanId, setScanId] = useState("");
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("PENDING");
  const [grade, setGrade] = useState("");
  const [symbol, setSymbol] = useState("");
  const [page, setPage] = useState(1);

  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [publishCandidate, setPublishCandidate] = useState<Candidate | null>(null);
  const [entry, setEntry] = useState("");
  const [target, setTarget] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  const [rejectCandidate, setRejectCandidate] = useState<Candidate | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  const scans = useApiData<Page<Scan>>("/admin/scans?page=1&page_size=100");
  const path = `/admin/candidates${buildQuery({
    page,
    page_size: PAGE_SIZE,
    scan_id: scanId,
    direction,
    status,
    grade,
    symbol
  })}`;
  const { data, loading, error, reload } = useApiData<Page<Candidate>>(path);

  function resetPage() {
    setPage(1);
  }

  async function approve(candidate: Candidate) {
    setBusyId(candidate.id);
    setActionError(null);
    setMessage(null);
    try {
      await api.post(`/admin/candidates/${candidate.id}/approve`);
      setMessage(`${candidate.symbol} ${candidate.direction} approved. It is now available under the APPROVED filter for publishing.`);
      setStatus("APPROVED");
      setPage(1);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusyId(null);
    }
  }

  function openPublish(candidate: Candidate) {
    const ltp = Number(candidate.scan_ltp);
    const isLong = candidate.direction === "LONG";
    setPublishCandidate(candidate);
    setEntry(String(ltp));
    setTarget((ltp * (isLong ? 1.05 : 0.95)).toFixed(2));
    setStopLoss((ltp * (isLong ? 0.98 : 1.02)).toFixed(2));
    setPublishError(null);
  }

  async function submitPublish(event: React.FormEvent) {
    event.preventDefault();
    if (!publishCandidate) return;
    setPublishing(true);
    setPublishError(null);
    try {
      const signal = await api.post<Signal>(`/admin/candidates/${publishCandidate.id}/publish`, {
        entry_price: entry,
        target_price: target,
        stop_loss: stopLoss.trim() === "" ? null : stopLoss
      });
      setMessage(
        `${signal.symbol} ${signal.direction} published as ACTIVE. Signal ${signal.id.slice(0, 8)}.`
      );
      setPublishCandidate(null);
      reload();
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  async function submitReject(event: React.FormEvent) {
    event.preventDefault();
    if (!rejectCandidate) return;
    setRejectError(null);
    try {
      await api.post(`/admin/candidates/${rejectCandidate.id}/reject`, {
        reason: rejectReason.trim() || null
      });
      setMessage(`${rejectCandidate.symbol} ${rejectCandidate.direction} rejected.`);
      setRejectCandidate(null);
      setRejectReason("");
      reload();
    } catch (err) {
      setRejectError(err instanceof Error ? err.message : "Rejection failed");
    }
  }

  return (
    <>
      {message ? <div className="success-text">{message}</div> : null}
      <Card
        title="Candidates"
        actions={
          <button className="btn ghost small" onClick={reload}>
            Refresh
          </button>
        }
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field label="Scan">
            <select value={scanId} onChange={(event) => { setScanId(event.target.value); resetPage(); }}>
              <option value="">All scans</option>
              {scans.data?.items.map((scan) => (
                <option key={scan.id} value={scan.id}>
                  {formatDateTime(scan.started_at)} · {scan.status}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Direction">
            <select value={direction} onChange={(event) => { setDirection(event.target.value); resetPage(); }}>
              <option value="">Both</option>
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
          </Field>
          <Field label="Status">
            <select value={status} onChange={(event) => { setStatus(event.target.value); resetPage(); }}>
              <option value="">All</option>
              {["PENDING", "APPROVED", "REJECTED", "PUBLISHED", "EXPIRED"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </Field>
          <Field label="Grade">
            <select value={grade} onChange={(event) => { setGrade(event.target.value); resetPage(); }}>
              <option value="">All</option>
              {["A+", "A", "B+", "B", "C"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </Field>
          <Field label="Symbol" hint="Contains">
            <input value={symbol} onChange={(event) => { setSymbol(event.target.value.toUpperCase()); resetPage(); }} placeholder="WIPRO" />
          </Field>
        </div>

        <ErrorText error={error || actionError} />

        {loading && !data ? (
          <Spinner label="Loading candidates" />
        ) : data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Grade</th>
                    <th className="right">Score</th>
                    <th className="right">Scan LTP</th>
                    <th className="right">Confirmations</th>
                    <th>Reason</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((candidate) => (
                    <tr key={candidate.id}>
                      <td className="nowrap strong">{candidate.symbol}</td>
                      <td>
                        <Badge tone={candidate.direction === "LONG" ? "green" : "red"}>
                          {candidate.direction}
                        </Badge>
                      </td>
                      <td><Badge tone={candidate.grade.startsWith("A") ? "green" : "blue"}>{candidate.grade}</Badge></td>
                      <td className="right">{num(candidate.score, 0)}</td>
                      <td className="right">{num(candidate.scan_ltp)}</td>
                      <td className="right">{candidate.confirmation_count}</td>
                      <td className="small muted" style={{ maxWidth: 280 }}>{candidate.reason}</td>
                      <td><Badge tone={toneForStatus(candidate.status)}>{candidate.status}</Badge></td>
                      <td className="nowrap">
                        <div className="flex">
                          {candidate.status !== "PUBLISHED" && candidate.status !== "EXPIRED" ? (
                            <>
                              <button
                                className="btn ghost small"
                                disabled={busyId === candidate.id || candidate.status === "APPROVED"}
                                onClick={() => approve(candidate)}
                                title={candidate.status === "APPROVED" ? "Already approved" : "Approve"}
                              >
                                Approve
                              </button>
                              <button
                                className="btn danger small"
                                onClick={() => { setRejectCandidate(candidate); setRejectReason(""); setRejectError(null); }}
                              >
                                Reject
                              </button>
                              {candidate.status === "APPROVED" ? (
                                <button className="btn small" onClick={() => openPublish(candidate)}>
                                  Publish
                                </button>
                              ) : null}
                            </>
                          ) : (
                            <span className="muted small">Published</span>
                          )}
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
          <Empty message="No candidates match these filters." />
        )}
      </Card>

      <Modal
        open={Boolean(publishCandidate)}
        title={publishCandidate ? `Publish ${publishCandidate.symbol} ${publishCandidate.direction}` : "Publish"}
        onClose={() => setPublishCandidate(null)}
      >
        {publishCandidate ? (
          <form onSubmit={submitPublish}>
            <div className="muted small" style={{ marginBottom: 12 }}>
              Scan LTP {num(publishCandidate.scan_ltp)} · Grade {publishCandidate.grade} · Score {num(publishCandidate.score, 0)}
            </div>
            <div className="form-grid">
              <Field label="Entry price">
                <input type="number" step="0.0001" min="0.0001" value={entry} onChange={(event) => setEntry(event.target.value)} required />
              </Field>
              <Field
                label="Target"
                hint={publishCandidate.direction === "LONG" ? "Must be above entry" : "Must be below entry"}
              >
                <input type="number" step="0.0001" min="0.0001" value={target} onChange={(event) => setTarget(event.target.value)} required />
              </Field>
              <Field
                label="Stop-loss"
                hint={publishCandidate.direction === "LONG" ? "Below entry" : "Above entry"}
              >
                <input type="number" step="0.0001" min="0.0001" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} />
              </Field>
            </div>
            <ErrorText error={publishError} />
            <div className="muted small" style={{ marginTop: 10 }}>
              Publishing activates FYERS price tracking. No current price is shown until a live quote is observed.
            </div>
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setPublishCandidate(null)}>Cancel</button>
              <button type="submit" className="btn" disabled={publishing}>
                {publishing ? "Publishing…" : "Publish signal"}
              </button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(rejectCandidate)}
        title={rejectCandidate ? `Reject ${rejectCandidate.symbol} ${rejectCandidate.direction}` : "Reject"}
        onClose={() => setRejectCandidate(null)}
      >
        {rejectCandidate ? (
          <form onSubmit={submitReject}>
            <Field label="Reason (optional)">
              <textarea value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} placeholder="Why is this candidate rejected?" />
            </Field>
            <ErrorText error={rejectError} />
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setRejectCandidate(null)}>Cancel</button>
              <button type="submit" className="btn danger">Reject candidate</button>
            </div>
          </form>
        ) : null}
      </Modal>
    </>
  );
}
