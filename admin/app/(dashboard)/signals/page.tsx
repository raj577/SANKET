"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Modal, Pagination, Spinner } from "@/components/ui";
import { api, buildQuery } from "@/lib/api";
import {
  formatDateTime,
  istDateString,
  num,
  relativeTime,
  signedPercent,
  toneForFreshness,
  toneForStatus
} from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, Signal, SignalDetail } from "@/lib/types";

const PAGE_SIZE = 25;

export default function SignalsPage() {
  const [status, setStatus] = useState("");
  const [direction, setDirection] = useState("");
  const [symbol, setSymbol] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [detail, setDetail] = useState<SignalDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Signal | null>(null);
  const [editEntry, setEditEntry] = useState("");
  const [editTarget, setEditTarget] = useState("");
  const [editStop, setEditStop] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [closing, setClosing] = useState<Signal | null>(null);
  const [closeOutcome, setCloseOutcome] = useState("EXPIRED");
  const [closeReason, setCloseReason] = useState("");
  const [closeError, setCloseError] = useState<string | null>(null);

  const [cancelling, setCancelling] = useState<Signal | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelError, setCancelError] = useState<string | null>(null);

  const path = `/admin/signals${buildQuery({
    page,
    page_size: PAGE_SIZE,
    status,
    direction,
    symbol,
    date_from: dateFrom,
    date_to: dateTo
  })}`;
  const { data, loading, error, reload } = useApiData<Page<Signal>>(path);

  useEffect(() => {
    const timer = window.setInterval(reload, 20000);
    return () => window.clearInterval(timer);
  }, [reload]);

  async function openDetail(signal: Signal) {
    setDetailError(null);
    try {
      setDetail(await api.get<SignalDetail>(`/admin/signals/${signal.id}`));
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Unable to load signal");
    }
  }

  function openEdit(signal: Signal) {
    setEditing(signal);
    setEditEntry(signal.entry_price);
    setEditTarget(signal.target_price);
    setEditStop(signal.stop_loss ?? "");
    setEditError(null);
  }

  async function submitEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setEditError(null);
    try {
      await api.patch(`/admin/signals/${editing.id}`, {
        entry_price: editEntry,
        target_price: editTarget,
        stop_loss: editStop.trim() === "" ? null : editStop
      });
      setMessage(`${editing.symbol} signal updated.`);
      setEditing(null);
      reload();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setSaving(false);
    }
  }

  async function submitClose(event: React.FormEvent) {
    event.preventDefault();
    if (!closing) return;
    setCloseError(null);
    try {
      await api.post(`/admin/signals/${closing.id}/close`, {
        outcome: closeOutcome,
        reason: closeReason.trim() || null
      });
      setMessage(`${closing.symbol} closed as ${closeOutcome}.`);
      setClosing(null);
      setCloseReason("");
      reload();
    } catch (err) {
      setCloseError(err instanceof Error ? err.message : "Close failed");
    }
  }

  async function submitCancel(event: React.FormEvent) {
    event.preventDefault();
    if (!cancelling) return;
    setCancelError(null);
    try {
      await api.post(`/admin/signals/${cancelling.id}/cancel`, {
        reason: cancelReason.trim() || null
      });
      setMessage(`${cancelling.symbol} signal cancelled.`);
      setCancelling(null);
      setCancelReason("");
      reload();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : "Cancel failed");
    }
  }

  return (
    <>
      {message ? <div className="success-text">{message}</div> : null}

      <Card
        title="Published signals"
        actions={
          <button className="btn ghost small" onClick={reload}>
            Refresh
          </button>
        }
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field label="Status">
            <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
              <option value="">All</option>
              {["ACTIVE", "TARGET_HIT", "STOPLOSS_HIT", "EXPIRED", "CANCELLED"].map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </Field>
          <Field label="Direction">
            <select value={direction} onChange={(event) => { setDirection(event.target.value); setPage(1); }}>
              <option value="">Both</option>
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
          </Field>
          <Field label="Symbol">
            <input value={symbol} onChange={(event) => { setSymbol(event.target.value.toUpperCase()); setPage(1); }} placeholder="WIPRO" />
          </Field>
          <Field label="Published from">
            <input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} />
          </Field>
          <Field label="Published to">
            <input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} />
          </Field>
          <div className="flex" style={{ alignItems: "flex-end", gap: 8 }}>
            <button className="btn ghost small" onClick={() => { setDateFrom(istDateString()); setDateTo(istDateString()); setPage(1); }}>Today</button>
            <button className="btn ghost small" onClick={() => { setDateFrom(istDateString(1)); setDateTo(istDateString(1)); setPage(1); }}>Yesterday</button>
            <button className="btn ghost small" onClick={() => { setDateFrom(""); setDateTo(""); setPage(1); }}>Clear dates</button>
          </div>
        </div>

        <ErrorText error={error || actionError} />

        {loading && !data ? (
          <Spinner label="Loading signals" />
        ) : data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Status</th>
                    <th className="right">Scan LTP</th>
                    <th className="right">Entry</th>
                    <th className="right">Target</th>
                    <th className="right">Stop</th>
                    <th className="right">Current</th>
                    <th className="right">Move</th>
                    <th>Freshness</th>
                    <th className="right">P&amp;L</th>
                    <th>Published</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((signal) => (
                    <tr key={signal.id}>
                      <td className="nowrap strong">{signal.symbol}</td>
                      <td><Badge tone={signal.direction === "LONG" ? "green" : "red"}>{signal.direction}</Badge></td>
                      <td><Badge tone={toneForStatus(signal.status)}>{signal.status}</Badge></td>
                      <td className="right">{num(signal.scan_ltp)}</td>
                      <td className="right">{num(signal.entry_price)}</td>
                      <td className="right">
                        {num(signal.target_price)}
                        {signal.target_reached ? <div><Badge tone="green">TARGET REACHED</Badge></div> : null}
                      </td>
                      <td className="right">{signal.stop_loss ? num(signal.stop_loss) : "—"}</td>
                      <td className="right">{num(signal.current_ltp)}</td>
                      <td className={`right ${signal.signal_move_percent === null ? "" : signal.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                        {signedPercent(signal.signal_move_percent)}
                      </td>
                      <td>
                        <Badge tone={toneForFreshness(signal.price_freshness)}>{signal.price_freshness}</Badge>
                        <div className="muted small">{relativeTime(signal.price_updated_at)}</div>
                      </td>
                      <td className={`right ${signal.pnl_percent === null ? "" : signal.pnl_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                        {signedPercent(signal.pnl_percent)}
                      </td>
                      <td className="nowrap small">{formatDateTime(signal.published_at)}</td>
                      <td className="nowrap">
                        <div className="flex">
                          <button className="btn ghost small" onClick={() => openDetail(signal)}>Detail</button>
                          {signal.status === "ACTIVE" ? (
                            <>
                              <button className="btn ghost small" onClick={() => openEdit(signal)}>Edit</button>
                              <button className="btn ghost small" onClick={() => { setClosing(signal); setCloseOutcome("EXPIRED"); setCloseReason(""); setCloseError(null); }}>Close</button>
                              <button className="btn danger small" onClick={() => { setCancelling(signal); setCancelReason(""); setCancelError(null); }}>Cancel</button>
                            </>
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
          <Empty message="No signals match these filters." />
        )}
      </Card>

      <Modal open={Boolean(detail) || Boolean(detailError)} title={detail ? `${detail.symbol} ${detail.direction}` : "Signal detail"} onClose={() => { setDetail(null); setDetailError(null); }} wide>
        <ErrorText error={detailError} />
        {detail ? (
          <div style={{ display: "grid", gap: 16 }}>
            <dl className="kv">
              <dt>Status</dt>
              <dd><Badge tone={toneForStatus(detail.status)}>{detail.status}</Badge></dd>
              <dt>Grade / score</dt>
              <dd>{detail.grade || "—"} · {detail.score ? num(detail.score, 0) : "—"}</dd>
              <dt>Scan LTP</dt>
              <dd>{num(detail.scan_ltp)} at {formatDateTime(detail.scan_timestamp)}</dd>
              <dt>Move (scan → latest)</dt>
              <dd className={detail.signal_move_percent === null ? "" : detail.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}>
                {signedPercent(detail.signal_move_percent)}
              </dd>
              <dt>Target reached</dt>
              <dd>{detail.target_reached ? <Badge tone="green">YES</Badge> : "No"}</dd>
              <dt>Entry / target / stop</dt>
              <dd>{num(detail.entry_price)} / {num(detail.target_price)} / {detail.stop_loss ? num(detail.stop_loss) : "—"}</dd>
              <dt>Current LTP</dt>
              <dd>{num(detail.current_ltp)} · {detail.price_freshness}</dd>
              <dt>Published</dt>
              <dd>{formatDateTime(detail.published_at)}</dd>
              <dt>Target hit</dt>
              <dd>{formatDateTime(detail.target_hit_at)}</dd>
              <dt>Stop-loss hit</dt>
              <dd>{formatDateTime(detail.stoploss_hit_at)}</dd>
              <dt>Closed</dt>
              <dd>{formatDateTime(detail.closed_at)}</dd>
              <dt>Reason</dt>
              <dd>{detail.reason || "—"}</dd>
            </dl>
            <div>
              <div className="section-title">Price history</div>
              {detail.price_history.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Captured (IST)</th><th>Event</th><th className="right">LTP</th></tr>
                    </thead>
                    <tbody>
                      {detail.price_history.map((point) => (
                        <tr key={point.id}>
                          <td>{formatDateTime(point.captured_at)}</td>
                          <td><Badge tone={toneForStatus(point.event_type)}>{point.event_type}</Badge></td>
                          <td className="right">{num(point.ltp)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty">No live price has been observed yet.</div>
              )}
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal open={Boolean(editing)} title={editing ? `Edit ${editing.symbol} ${editing.direction}` : "Edit signal"} onClose={() => setEditing(null)}>
        {editing ? (
          <form onSubmit={submitEdit}>
            <div className="form-grid">
              <Field label="Entry price">
                <input type="number" step="0.0001" min="0.0001" value={editEntry} onChange={(event) => setEditEntry(event.target.value)} required />
              </Field>
              <Field label="Target price" hint={editing.direction === "LONG" ? "Above entry" : "Below entry"}>
                <input type="number" step="0.0001" min="0.0001" value={editTarget} onChange={(event) => setEditTarget(event.target.value)} required />
              </Field>
              <Field label="Stop-loss" hint={editing.direction === "LONG" ? "Below entry" : "Above entry"}>
                <input type="number" step="0.0001" min="0.0001" value={editStop} onChange={(event) => setEditStop(event.target.value)} />
              </Field>
            </div>
            <ErrorText error={editError} />
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal open={Boolean(closing)} title={closing ? `Close ${closing.symbol}` : "Close signal"} onClose={() => setClosing(null)}>
        {closing ? (
          <form onSubmit={submitClose}>
            <Field label="Outcome">
              <select value={closeOutcome} onChange={(event) => setCloseOutcome(event.target.value)}>
                <option value="EXPIRED">EXPIRED</option>
                <option value="TARGET_HIT">TARGET_HIT</option>
                <option value="STOPLOSS_HIT">STOPLOSS_HIT</option>
              </select>
            </Field>
            <Field label="Reason (optional)">
              <textarea value={closeReason} onChange={(event) => setCloseReason(event.target.value)} />
            </Field>
            <ErrorText error={closeError} />
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setClosing(null)}>Back</button>
              <button type="submit" className="btn">Close signal</button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal open={Boolean(cancelling)} title={cancelling ? `Cancel ${cancelling.symbol}` : "Cancel signal"} onClose={() => setCancelling(null)}>
        {cancelling ? (
          <form onSubmit={submitCancel}>
            <Field label="Reason (optional)">
              <textarea value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} />
            </Field>
            <ErrorText error={cancelError} />
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setCancelling(null)}>Back</button>
              <button type="submit" className="btn danger">Cancel signal</button>
            </div>
          </form>
        ) : null}
      </Modal>
    </>
  );
}
