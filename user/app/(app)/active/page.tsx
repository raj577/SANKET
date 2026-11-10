"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Pagination, Spinner } from "@/components/ui";
import { buildQuery } from "@/lib/api";
import { num, relativeTime, signedPercent, toneForFreshness } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, Signal } from "@/lib/types";

const PAGE_SIZE = 20;

function progress(value: number | null): number {
  if (value === null || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export default function ActiveSignalsPage() {
  const [direction, setDirection] = useState("");
  const [symbol, setSymbol] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const path = `/signals/active${buildQuery({
    page,
    page_size: PAGE_SIZE,
    direction,
    symbol,
    date_from: dateFrom,
    date_to: dateTo
  })}`;
  const { data, loading, error, reload } = useApiData<Page<Signal>>(path);

  useEffect(() => {
    const timer = window.setInterval(reload, 15000);
    return () => window.clearInterval(timer);
  }, [reload]);

  return (
    <Card
      title="Active signals"
      actions={<button className="btn ghost small" onClick={reload}>Refresh</button>}
    >
      <div className="filters" style={{ marginBottom: 14 }}>
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
      </div>

      <ErrorText error={error} />
      {loading && !data ? (
        <Spinner label="Loading active signals" />
      ) : data && data.items.length > 0 ? (
        <>
          <div className="signal-grid">
            {data.items.map((signal) => (
              <Link key={signal.id} href={`/signals/${signal.id}`} className="signal-card">
                <div className="flex" style={{ justifyContent: "space-between" }}>
                  <div className="flex">
                    <strong className="signal-symbol">{signal.symbol}</strong>
                    <Badge tone={signal.direction === "LONG" ? "green" : "red"}>{signal.direction}</Badge>
                    {signal.target_reached ? <Badge tone="green">TARGET REACHED</Badge> : null}
                  </div>
                  <Badge tone={toneForFreshness(signal.price_freshness)}>{signal.price_freshness}</Badge>
                </div>
                <div className="signal-prices">
                  <div>
                    <span className="stat-label">Scan LTP</span>
                    <strong>{num(signal.scan_ltp)}</strong>
                  </div>
                  <div>
                    <span className="stat-label">Current</span>
                    <strong>{num(signal.current_ltp)}</strong>
                  </div>
                  <div>
                    <span className="stat-label">Move</span>
                    <strong className={signal.signal_move_percent === null ? "" : signal.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}>
                      {signedPercent(signal.signal_move_percent)}
                    </strong>
                  </div>
                </div>
                <div className="signal-prices">
                  <div>
                    <span className="stat-label">Entry</span>
                    <strong>{num(signal.entry_price)}</strong>
                  </div>
                  <div>
                    <span className="stat-label">Target</span>
                    <strong>{num(signal.target_price)}</strong>
                  </div>
                  <div>
                    <span className="stat-label">P&amp;L</span>
                    <strong className={signal.pnl_percent === null ? "" : signal.pnl_percent >= 0 ? "pnl-pos" : "pnl-neg"}>
                      {signedPercent(signal.pnl_percent)}
                    </strong>
                  </div>
                </div>
                <div className="progress-track" title="Progress toward target">
                  <div className="progress-fill" style={{ width: `${progress(signal.target_progress_percent)}%` }} />
                </div>
                <div className="flex" style={{ justifyContent: "space-between", marginTop: 8 }}>
                  <span className="muted small">Target {num(signal.target_price)} · SL {signal.stop_loss ? num(signal.stop_loss) : "—"}</span>
                  <span className="muted small">{relativeTime(signal.price_updated_at)}</span>
                </div>
              </Link>
            ))}
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      ) : (
        <Empty message="No active signals match these filters." />
      )}
    </Card>
  );
}
