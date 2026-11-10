"use client";

import Link from "next/link";

import { Badge, Card, ErrorText, Spinner, StatCard } from "@/components/ui";
import { relativeTime, formatDateTime, istDateString, num, signedPercent, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { DashboardOverview, Page, Scan, Signal } from "@/lib/types";

export default function OverviewPage() {
  const today = istDateString();
  const yesterday = istDateString(1);
  const overview = useApiData<DashboardOverview>("/admin/overview");
  const scans = useApiData<Page<Scan>>("/admin/scans?page=1&page_size=6");
  const todaysSignals = useApiData<Page<Signal>>(
    `/admin/signals?page=1&page_size=10&date_from=${today}&date_to=${today}`
  );
  const yesterdaysSignals = useApiData<Page<Signal>>(
    `/admin/signals?page=1&page_size=10&date_from=${yesterday}&date_to=${yesterday}`
  );

  if (overview.loading && !overview.data) return <Spinner label="Loading overview" />;

  return (
    <>
      <ErrorText
        error={overview.error || scans.error || todaysSignals.error || yesterdaysSignals.error}
      />

      <div className="stat-grid">
        <StatCard label="Scans today" value={overview.data?.today_scans ?? "—"} hint={`${overview.data?.successful_scans ?? 0} completed · ${overview.data?.failed_scans ?? 0} failed`} tone="blue" />
        <StatCard label="Stocks scanned" value={overview.data?.total_scanned_stocks ?? "—"} hint="Successful symbol reads today" />
        <StatCard label="LONG candidates" value={overview.data?.long_candidates ?? "—"} hint="Filtered today" tone="green" />
        <StatCard label="SHORT candidates" value={overview.data?.short_candidates ?? "—"} hint="Filtered today" tone="red" />
        <StatCard label="Pending approvals" value={overview.data?.pending_approvals ?? "—"} hint="Candidates awaiting review" tone="amber" />
        <StatCard label="Active signals" value={overview.data?.active_signals ?? "—"} hint={`${overview.data?.published_signals ?? 0} published overall`} tone="green" />
        <StatCard label="Target hits" value={overview.data?.target_hits ?? "—"} hint="Tracked by FYERS" tone="green" />
        <StatCard label="Stop-loss hits" value={overview.data?.stoploss_hits ?? "—"} hint="Tracked by FYERS" tone="red" />
        <StatCard label="CSV archives" value={overview.data?.csv_archive_count ?? "—"} hint="Permanent originals" tone="blue" />
      </div>

      <div className="split">
        <AdminSignalDayCard title="Today's signals" signals={todaysSignals} />
        <AdminSignalDayCard title="Yesterday's signals" signals={yesterdaysSignals} />
      </div>

      <div className="split">
        <Card title="System status">
          <dl className="kv">
            <dt>Collector authentication</dt>
            <dd>
              <Badge tone={overview.data?.collector_status === "CONFIGURED" ? "green" : "amber"}>
                {overview.data?.collector_status === "CONFIGURED" ? "Configured" : "Not configured"}
              </Badge>
              <span className="muted small"> The extension needs a collector token.</span>
            </dd>
            <dt>Market data</dt>
            <dd>
              <Badge tone={overview.data?.market_data_status === "CONFIGURED" ? "green" : "amber"}>
                {overview.data?.market_data_status === "CONFIGURED" ? "Configured" : "Not configured"}
              </Badge>
              <span className="muted small">
                {" "}
                {overview.data?.market_data_provider ?? "FYERS"} ·{" "}
                {overview.data?.stream_transport === "websocket" ? "SFeed websocket" : "REST quotes"}.
                Prices appear only after a live quote is observed.
              </span>
            </dd>
            <dt>Price freshness rule</dt>
            <dd className="muted small">UNKNOWN until the provider returns an LTP; LIVE, DELAYED and STALE follow the configured poll windows.</dd>
          </dl>
        </Card>

        <Card
          title="Latest scans"
          actions={
            <Link className="btn ghost small" href="/scans">
              View all
            </Link>
          }
        >
          {scans.loading && !scans.data ? (
            <Spinner label="Loading scans" />
          ) : scans.data && scans.data.items.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Status</th>
                    <th className="right">LONG</th>
                    <th className="right">SHORT</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.data.items.map((scan) => (
                    <tr key={scan.id}>
                      <td>
                        <div>{formatDateTime(scan.started_at)}</div>
                        <span className="muted small">{relativeTime(scan.started_at)}</span>
                      </td>
                      <td>
                        <Badge tone={toneForStatus(scan.status)}>{scan.status}</Badge>
                      </td>
                      <td className="right">{scan.long_candidates_count}</td>
                      <td className="right">{scan.short_candidates_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">No scans have been uploaded yet.</div>
          )}
        </Card>
      </div>
    </>
  );
}

function AdminSignalDayCard({
  title,
  signals
}: {
  title: string;
  signals: ReturnType<typeof useApiData<Page<Signal>>>;
}) {
  return (
    <Card title={title}>
      {signals.loading && !signals.data ? (
        <Spinner label={`Loading ${title.toLowerCase()}`} />
      ) : signals.data && signals.data.items.length > 0 ? (
        <div style={{ display: "grid", gap: 10 }}>
          {signals.data.items.map((signal) => (
            <div key={signal.id} className="history-item">
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
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">{`No signals published ${title === "Today's signals" ? "today" : "yesterday"}.`}</div>
      )}
    </Card>
  );
}
