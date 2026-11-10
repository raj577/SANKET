"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";

import { PriceChart } from "@/components/price-chart";
import { Badge, Card, ErrorText, Spinner } from "@/components/ui";
import { useApiData } from "@/lib/use-api-data";
import {
  formatDateTime,
  num,
  relativeTime,
  signedPercent,
  toneForFreshness,
  toneForStatus
} from "@/lib/format";
import type { SignalDetail } from "@/lib/types";

function progress(value: number | null): number {
  if (value === null || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export default function SignalDetailPage() {
  const params = useParams();
  const id = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const { data, loading, error, reload } = useApiData<SignalDetail>(
    id ? `/signals/${id}` : null
  );

  useEffect(() => {
    if (!data || data.status !== "ACTIVE") return;
    const timer = window.setInterval(reload, 20000);
    return () => window.clearInterval(timer);
  }, [data, reload]);

  if (loading && !data) return <Spinner label="Loading signal" />;
  if (error) return <ErrorText error={error} />;
  if (!data) return null;

  const isActive = data.status === "ACTIVE";
  const clickable = isActive ? "LIVE" : null;

  return (
    <>
      <div className="flex" style={{ justifyContent: "space-between" }}>
        <Link className="btn ghost small" href="/active">← Active signals</Link>
        <button className="btn ghost small" onClick={reload}>Refresh</button>
      </div>

      <Card>
        <div className="detail-head">
          <div>
            <div className="flex">
              <h2 className="detail-symbol">{data.symbol}</h2>
              <Badge tone={data.direction === "LONG" ? "green" : "red"}>{data.direction}</Badge>
              <Badge tone={toneForStatus(data.status)}>{data.status}</Badge>
              {data.target_reached ? <Badge tone="green">TARGET REACHED</Badge> : null}
              <Badge tone={toneForFreshness(data.price_freshness)}>{data.price_freshness}</Badge>
              {clickable ? <span className="pulse" title="Price updates while active" /> : null}
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>
              Published {formatDateTime(data.published_at)} · {data.grade || "—"} grade
              {data.score ? ` · score ${num(data.score, 0)}` : ""}
            </div>
          </div>
          <div className="detail-pnl">
            <span className="stat-label">Unrealised P&amp;L</span>
            <strong className={data.pnl_percent === null ? "" : data.pnl_percent >= 0 ? "pnl-pos" : "pnl-neg"}>
              {signedPercent(data.pnl_percent)}
            </strong>
          </div>
        </div>

        <div className="detail-metrics">
          <div className="metric">
            <span className="stat-label">Entry</span>
            <strong>{num(data.entry_price)}</strong>
          </div>
          <div className="metric">
            <span className="stat-label">Current LTP</span>
            <strong>{num(data.current_ltp)}</strong>
            <span className="muted small">{relativeTime(data.price_updated_at)}</span>
          </div>
          <div className="metric">
            <span className="stat-label">Target</span>
            <strong>{num(data.target_price)}</strong>
          </div>
          <div className="metric">
            <span className="stat-label">Stop-loss</span>
            <strong>{data.stop_loss ? num(data.stop_loss) : "—"}</strong>
          </div>
          <div className="metric">
            <span className="stat-label">Scan LTP</span>
            <strong>{num(data.scan_ltp)}</strong>
            <span className="muted small">{formatDateTime(data.scan_timestamp)}</span>
          </div>
          <div className="metric">
            <span className="stat-label">Move (scan → latest)</span>
            <strong className={data.signal_move_percent === null ? "" : data.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}>
              {signedPercent(data.signal_move_percent)}
            </strong>
          </div>
        </div>

        <div style={{ marginTop: 18 }}>
          <div className="flex" style={{ justifyContent: "space-between" }}>
            <span className="stat-label">Progress to target</span>
            <span className="muted small">
              {data.target_progress_percent === null ? "—" : `${data.target_progress_percent.toFixed(1)}%`}
            </span>
          </div>
          <div className="progress-track" style={{ height: 8, marginTop: 6 }}>
            <div className="progress-fill" style={{ width: `${progress(data.target_progress_percent)}%` }} />
          </div>
        </div>

        {data.status !== "ACTIVE" ? (
          <div className="closed-note">
            {data.status === "TARGET_HIT" ? `Target hit ${formatDateTime(data.target_hit_at)}` : null}
            {data.status === "STOPLOSS_HIT" ? `Stop-loss hit ${formatDateTime(data.stoploss_hit_at)}` : null}
            {data.status === "EXPIRED" ? `Expired ${formatDateTime(data.closed_at)}` : null}
            {data.status === "CANCELLED" ? `Cancelled ${formatDateTime(data.closed_at)}` : null}
          </div>
        ) : null}
      </Card>

      <Card title="Observed price history">
        {data.price_history.length ? (
          <PriceChart
            points={data.price_history}
            entry={data.entry_price}
            target={data.target_price}
            stopLoss={data.stop_loss}
            direction={data.direction}
          />
        ) : (
          <div className="empty">
            No live price has been observed yet. The signal stays UNKNOWN until FYERS returns an LTP.
          </div>
        )}
        {data.price_history.length ? (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table>
              <thead>
                <tr>
                  <th>Captured (IST)</th>
                  <th>Event</th>
                  <th className="right">LTP</th>
                </tr>
              </thead>
              <tbody>
                {data.price_history.map((point) => (
                  <tr key={point.id}>
                    <td>{formatDateTime(point.captured_at)}</td>
                    <td><Badge tone={toneForStatus(point.event_type)}>{point.event_type}</Badge></td>
                    <td className="right">{num(point.ltp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <Card title="Why this signal">
        <div style={{ display: "grid", gap: 8 }}>
          <div className="muted small">
            Scanner reason: <span style={{ color: "var(--text)" }}>{data.reason || "—"}</span>
          </div>
          <div className="muted small">
            Entry, target and stop-loss are administrator decisions. The current LTP is the last observation actually returned by FYERS; it is never simulated.
          </div>
        </div>
      </Card>
    </>
  );
}
