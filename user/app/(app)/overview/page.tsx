"use client";

import Link from "next/link";

import { Badge, Card, Empty, ErrorText, Spinner, StatCard } from "@/components/ui";
import { formatDateTime, istDateString, num, relativeTime, signedPercent, toneForFreshness, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, Signal, SignalSummary } from "@/lib/types";

export default function OverviewPage() {
  const today = istDateString();
  const yesterday = istDateString(1);
  const summary = useApiData<SignalSummary>("/signals/summary");
  const active = useApiData<Page<Signal>>("/signals/active?page=1&page_size=5");
  const todaysSignals = useApiData<Page<Signal>>(
    `/signals?page=1&page_size=10&date_from=${today}&date_to=${today}`
  );
  const yesterdaysSignals = useApiData<Page<Signal>>(
    `/signals?page=1&page_size=10&date_from=${yesterday}&date_to=${yesterday}`
  );

  if (summary.loading && !summary.data) return <Spinner label="Loading dashboard" />;

  return (
    <>
      <ErrorText
        error={summary.error || active.error || todaysSignals.error || yesterdaysSignals.error}
      />

      <div className="stat-grid">
        <StatCard label="Active signals" value={summary.data?.active ?? "—"} hint="Currently tracked" tone="green" />
        <StatCard label="Signals today" value={summary.data?.today_published ?? "—"} hint={`${summary.data?.target_hits_today ?? 0} reached target`} tone="blue" />
        <StatCard label="Signals yesterday" value={summary.data?.yesterday_published ?? "—"} hint={`${summary.data?.target_hits_yesterday ?? 0} reached target`} tone="blue" />
        <StatCard label="Target hits" value={summary.data?.target_hit ?? "—"} hint="Closed at target" tone="green" />
        <StatCard label="Stop-loss hits" value={summary.data?.stoploss_hit ?? "—"} hint="Closed at stop" tone="red" />
        <StatCard label="Published total" value={summary.data?.total ?? "—"} hint={`${summary.data?.expired ?? 0} expired · ${summary.data?.cancelled ?? 0} cancelled`} tone="blue" />
      </div>

      <Card
        title="Latest active signals"
        actions={
          <Link className="btn ghost small" href="/active">
            View all
          </Link>
        }
      >
        {active.loading && !active.data ? (
          <Spinner label="Loading signals" />
        ) : active.data && active.data.items.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Direction</th>
                  <th className="right">Scan LTP</th>
                  <th className="right">Current</th>
                  <th>Freshness</th>
                  <th className="right">Move</th>
                  <th className="right">P&amp;L</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {active.data.items.map((signal) => (
                  <tr key={signal.id}>
                    <td className="strong">{signal.symbol}</td>
                    <td><Badge tone={signal.direction === "LONG" ? "green" : "red"}>{signal.direction}</Badge></td>
                    <td className="right">{num(signal.scan_ltp)}</td>
                    <td className="right">{num(signal.current_ltp)}</td>
                    <td>
                      <Badge tone={toneForFreshness(signal.price_freshness)}>{signal.price_freshness}</Badge>
                      <div className="muted small">{relativeTime(signal.price_updated_at)}</div>
                    </td>
                    <td className={`right ${signal.signal_move_percent === null ? "" : signal.signal_move_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                      {signedPercent(signal.signal_move_percent)}
                    </td>
                    <td className={`right ${signal.pnl_percent === null ? "" : signal.pnl_percent >= 0 ? "pnl-pos" : "pnl-neg"}`}>
                      {signedPercent(signal.pnl_percent)}
                    </td>
                    <td>
                      <Link className="btn ghost small" href={`/signals/${signal.id}`}>
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty message="No active signals right now." />
        )}
      </Card>

      <div className="split">
        <SignalDayCard title="Today's signals" signals={todaysSignals} loading={todaysSignals.loading} />
        <SignalDayCard title="Yesterday's signals" signals={yesterdaysSignals} loading={yesterdaysSignals.loading} />
      </div>

      <Card title="Last live quote">
        <div className="stat-value" style={{ fontSize: 20 }}>
          {summary.data?.last_price_update ? relativeTime(summary.data.last_price_update) : "No live quote yet"}
        </div>
        <div className="muted small" style={{ marginTop: 6 }}>
          {summary.data?.last_price_update
            ? formatDateTime(summary.data.last_price_update)
            : "A price is only shown after FYERS returns an observation."}
        </div>
      </Card>
    </>
  );
}

function SignalDayCard({
  title,
  signals,
  loading
}: {
  title: string;
  signals: ReturnType<typeof useApiData<Page<Signal>>>;
  loading: boolean;
}) {
  return (
    <Card
      title={title}
      actions={
        <Link className="btn ghost small" href={`/history`}>
          History
        </Link>
      }
    >
      {loading && !signals.data ? (
        <Spinner label={`Loading ${title.toLowerCase()}`} />
      ) : signals.data && signals.data.items.length > 0 ? (
        <div style={{ display: "grid", gap: 10 }}>
          {signals.data.items.map((signal) => (
            <Link key={signal.id} href={`/signals/${signal.id}`} className="history-item" style={{ display: "block" }}>
              <div className="flex" style={{ justifyContent: "space-between" }}>
                <span>
                  <strong>{signal.symbol}</strong>{" "}
                  <Badge tone={signal.direction === "LONG" ? "green" : "red"}>{signal.direction}</Badge>{" "}
                  {signal.target_reached ? <Badge tone="green">TARGET</Badge> : null}
                </span>
                <Badge tone={toneForStatus(signal.status)}>{signal.status}</Badge>
              </div>
              <div className="muted small" style={{ marginTop: 4 }}>
                Scan {num(signal.scan_ltp)} → {num(signal.current_ltp)} · Move {signedPercent(signal.signal_move_percent)} · {formatDateTime(signal.published_at)}
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty message={`No signals published ${title === "Today's signals" ? "today" : "yesterday"}.`} />
      )}
    </Card>
  );
}
