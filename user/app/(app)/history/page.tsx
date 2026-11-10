"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Pagination, Spinner } from "@/components/ui";
import { buildQuery } from "@/lib/api";
import { formatDateTime, num, signedPercent, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, Signal } from "@/lib/types";

const PAGE_SIZE = 25;

export default function HistoryPage() {
  const [status, setStatus] = useState("");
  const [symbol, setSymbol] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const path = `/signals${buildQuery({
    page,
    page_size: PAGE_SIZE,
    status,
    symbol,
    date_from: dateFrom,
    date_to: dateTo
  })}`;
  const { data, loading, error, reload } = useApiData<Page<Signal>>(path);

  return (
    <Card
      title="Signal history"
      actions={<button className="btn ghost small" onClick={reload}>Refresh</button>}
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
        <Spinner label="Loading history" />
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
                  <th className="right">Latest LTP</th>
                  <th className="right">Move</th>
                  <th className="right">Entry</th>
                  <th className="right">Target</th>
                  <th className="right">Stop</th>
                  <th className="right">P&amp;L</th>
                  <th>Published</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((signal) => (
                  <tr key={signal.id}>
                    <td className="strong">{signal.symbol}</td>
                    <td><Badge tone={signal.direction === "LONG" ? "green" : "red"}>{signal.direction}</Badge></td>
                    <td><Badge tone={toneForStatus(signal.status)}>{signal.status}</Badge></td>
                    <td className="right">{num(signal.scan_ltp)}</td>
                    <td className="right">{num(signal.current_ltp)}</td>
                    <td className={`right ${signal.signal_move_percent === null ? "" : signal.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                      {signedPercent(signal.signal_move_percent)}
                      {signal.target_reached ? <div><Badge tone="green">TARGET</Badge></div> : null}
                    </td>
                    <td className="right">{num(signal.entry_price)}</td>
                    <td className="right">{num(signal.target_price)}</td>
                    <td className="right">{signal.stop_loss ? num(signal.stop_loss) : "—"}</td>
                    <td className={`right ${signal.pnl_percent === null ? "" : signal.pnl_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                      {signedPercent(signal.pnl_percent)}
                    </td>
                    <td className="nowrap small">{formatDateTime(signal.published_at)}</td>
                    <td>
                      <Link className="btn ghost small" href={`/signals/${signal.id}`}>Open</Link>
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
  );
}
