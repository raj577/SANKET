"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Badge,
  Card,
  Empty,
  ErrorText,
  Field,
  ProgressBar,
  Spinner,
  StatCard
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  formatDate,
  formatDateTime,
  istDateString,
  num,
  relativeTime,
  signedPercent
} from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type {
  CandleBackfill,
  PerformanceCoverage,
  PerformanceDay,
  PerformanceExtreme,
  PerformanceHighLow,
  PerformanceOffset,
  PerformanceReport,
  PerformanceSymbol
} from "@/lib/types";

const FORWARD_CHOICES = [3, 5, 10];

type StatusFilter = "all" | "approved" | "not_approved";

const STATUS_CHOICES: { value: StatusFilter; label: string; title: string }[] = [
  {
    value: "all",
    label: "All stocks",
    title: "Every candidate the scanner filtered"
  },
  {
    value: "approved",
    label: "Approved",
    title: "Candidates marked APPROVED or PUBLISHED"
  },
  {
    value: "not_approved",
    label: "Not approved",
    title: "Candidates still PENDING or REJECTED"
  }
];

function returnClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "muted";
  if (value > 0) return "pnl-pos";
  if (value < 0) return "pnl-neg";
  return "muted";
}

function coverageTone(coverage: PerformanceCoverage) {
  switch (coverage) {
    case "COMPLETE":
      return "green" as const;
    case "PARTIAL":
      return "amber" as const;
    case "PENDING":
      return "blue" as const;
    default:
      return "red" as const;
  }
}

function offsetLabel(index: number): string {
  return `D+${index + 1}`;
}

function winRateText(offset: PerformanceOffset | undefined): string {
  if (!offset || offset.win_rate_pct === null || offset.win_rate_pct === undefined) {
    return "—";
  }
  return `${offset.win_rate_pct}%`;
}

function OffsetCell({
  offset,
  strong = false
}: {
  offset: PerformanceOffset | undefined;
  strong?: boolean;
}) {
  if (!offset?.n) {
    return <td className="right muted">—</td>;
  }
  return (
    <td className={`right ${returnClass(offset.avg_return_pct)}`}>
      {strong ? <strong>{signedPercent(offset.avg_return_pct)}</strong> : signedPercent(offset.avg_return_pct)}
      <span className="muted small">
        {" · "}
        {offset.n} · {winRateText(offset)} win
      </span>
    </td>
  );
}

function ExtremeCell({
  extreme,
  returnPct
}: {
  extreme: PerformanceExtreme | undefined;
  returnPct: number | null | undefined;
}) {
  if (!extreme || extreme.offset === null || extreme.price === null) {
    return <span className="muted small">—</span>;
  }
  return (
    <>
      <strong>D+{extreme.offset}</strong>
      <div className="muted small">
        {num(extreme.price)} · {signedPercent(returnPct)}
      </div>
    </>
  );
}

function SignalFit({ summary }: { summary: PerformanceHighLow | null | undefined }) {
  if (!summary || summary.favourable === null || summary.favourable === undefined) {
    return <span className="muted small">—</span>;
  }
  const extreme = summary.favourable_role === "long" ? summary.highest : summary.lowest;
  const day = extreme.offset === null ? "—" : `D+${extreme.offset}`;
  const title = `${summary.actual_direction} at its ${
    summary.favourable_role === "long" ? "highest high" : "lowest low"
  }: ${signedPercent(summary.favourable_return_pct)} (worst point ${signedPercent(
    summary.adverse_return_pct
  )})`;
  return (
    <span title={title}>
      <Badge tone={summary.favourable ? "green" : "red"}>
        {summary.actual_direction} {summary.favourable ? "✓" : "✗"} {day}
      </Badge>
    </span>
  );
}

export default function PerformancePage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [forwardDays, setForwardDays] = useState(5);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [refreshJob, setRefreshJob] = useState<CandleBackfill | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Set the default window after mount so the server and client render the
  // same empty state instead of disagreeing on "today".
  useEffect(() => {
    if (!dateFrom && !dateTo) {
      setDateFrom(istDateString(30));
      setDateTo(istDateString(0));
    }
  }, [dateFrom, dateTo]);

  const path =
    dateFrom && dateTo
      ? `/admin/performance?date_from=${dateFrom}&date_to=${dateTo}&forward_days=${forwardDays}&status=${statusFilter}`
      : null;
  const { data, loading, error, reload } = useApiData<PerformanceReport>(path);
  const latest = useApiData<CandleBackfill | null>("/admin/performance/backfill/latest");

  useEffect(() => {
    if (latest.data) setRefreshJob(latest.data);
  }, [latest.data]);

  useEffect(() => {
    if (!refreshJob || refreshJob.state === "finished") return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.get<CandleBackfill>(
          `/admin/performance/backfill/${refreshJob.run_id}`
        );
        if (!active) return;
        setRefreshJob(next);
        if (next.state === "finished") {
          setMessage(
            `Candle refresh ${next.status.toLowerCase()}: ${next.processed_symbols}/${next.total_symbols} symbols processed, ${next.candles_written} candles stored.`
          );
          reload();
          latest.reload();
        }
      } catch (err) {
        if (!active) return;
        setActionError(
          err instanceof Error ? err.message : "Unable to read refresh progress"
        );
      }
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshJob, reload, latest.reload]);

  const refreshing = refreshJob !== null && refreshJob.state !== "finished";

  async function startRefresh() {
    setStarting(true);
    setActionError(null);
    setMessage(null);
    try {
      const job = await api.post<CandleBackfill>("/admin/performance/backfill", {
        date_from: dateFrom,
        date_to: dateTo,
        forward_days: forwardDays
      });
      setRefreshJob(job);
      setMessage("Candle refresh queued. FYERS history is paced, so this can take a few minutes.");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unable to start the candle refresh");
    } finally {
      setStarting(false);
    }
  }

  const totals = data?.totals;
  const stockLabel =
    statusFilter === "approved"
      ? "Approved stocks"
      : statusFilter === "not_approved"
        ? "Not approved stocks"
        : "Filtered stocks";
  const d1 = totals?.offsets?.[0];
  const d3 = totals?.offsets?.[2];
  const cache = data?.cache;
  const missingCount = data?.missing_symbols.length ?? 0;
  const staleCache =
    Boolean(cache?.data_to) && Boolean(dateTo) && (cache?.data_to ?? "") < dateTo;

  const failedSymbols = useMemo(
    () => (refreshJob?.symbols ?? []).filter((row) => row.state === "ERROR").slice(0, 12),
    [refreshJob]
  );

  return (
    <>
      <Card
        title="Day-wise performance"
        actions={
          <>
            <button className="btn small ghost" onClick={reload} disabled={!path}>
              Reload report
            </button>
            <button className="btn small" onClick={startRefresh} disabled={starting || refreshing || !path}>
              {refreshing ? "Refreshing candles…" : "Refresh candle data"}
            </button>
          </>
        }
      >
        <div className="filters">
          <Field label="From">
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </Field>
          <Field label="Forward sessions">
            <select
              value={forwardDays}
              onChange={(event) => setForwardDays(Number(event.target.value))}
            >
              {FORWARD_CHOICES.map((choice) => (
                <option key={choice} value={choice}>
                  {choice} sessions
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stock set">
            <div className="segmented" role="group" aria-label="Filter stocks by review status">
              {STATUS_CHOICES.map((choice) => {
                const active = statusFilter === choice.value;
                return (
                  <button
                    key={choice.value}
                    type="button"
                    className={`segmented-btn${active ? " active" : ""}`}
                    aria-pressed={active}
                    title={choice.title}
                    onClick={() => setStatusFilter(choice.value)}
                  >
                    {choice.label}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>

        <p className="performance-note">
          {statusFilter === "approved"
            ? "Showing only approved stocks: candidates marked APPROVED (accepted for publishing) or PUBLISHED (signal sent)."
            : statusFilter === "not_approved"
              ? "Showing only stocks that are not approved: candidates still PENDING review or REJECTED."
              : "Showing every OI candidate: stocks that passed the scanner's filters, whatever their review status."}{" "}
          A return is the direction-adjusted move from the scan spot to that session's
          close. Only completed sessions are used, so today's forming candle is never D+1.
        </p>

        <ErrorText error={actionError || error || null} />
        {message ? <div className="success-text">{message}</div> : null}

        {refreshJob ? (
          <div className="performance-refresh">
            <div className="progress-head">
              <strong>
                Candle cache · {refreshJob.status} · {refreshJob.processed_symbols}/
                {refreshJob.total_symbols} symbols
              </strong>
              <span className="muted small">
                {refreshJob.fetched} with data · {refreshJob.no_data} empty ·{" "}
                {refreshJob.failed_symbols} failed · {refreshJob.candles_written} candles
                {refreshJob.current ? ` · ${refreshJob.current}` : ""}
              </span>
            </div>
            <ProgressBar
              value={refreshJob.percent}
              label="Candle backfill progress"
              tone={refreshJob.status === "FAILED" ? "red" : "blue"}
            />
            <div className="muted small">
              Requested {formatDate(refreshJob.range_from)} → {formatDate(refreshJob.range_to)}
              {refreshJob.completed_at
                ? ` · finished ${relativeTime(refreshJob.completed_at)}`
                : ""}
            </div>
            {refreshJob.error_message ? (
              <div className="notice-warn">
                {refreshJob.error_message}
                {/token|authenticate|login/i.test(refreshJob.error_message)
                  ? " Connect FYERS under Settings, then refresh again."
                  : ""}
              </div>
            ) : null}
            {failedSymbols.length ? (
              <details className="performance-failures">
                <summary className="small muted">
                  {refreshJob.failed_symbols} symbol(s) failed — show details
                </summary>
                <ul>
                  {failedSymbols.map((row) => (
                    <li key={row.symbol} className="small">
                      <strong>{row.symbol}</strong>: {row.message || "unknown error"}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}

        {missingCount > 0 ? (
          <div className="notice-warn">
            {missingCount} filtered symbol(s) have no cached candles, so their returns are
            blank. Use <em>Refresh candle data</em> for this window.
          </div>
        ) : null}
        {data && data.pending_days > 0 ? (
          <div className="notice-warn">
            {data.pending_days} scan day(s) have no completed forward session yet; their
            returns appear after the next market close.
          </div>
        ) : null}
        {staleCache ? (
          <div className="notice-warn">
            Cached candles end on {formatDate(cache?.data_to)}; later sessions may be
            missing. Refresh to extend the cache.
          </div>
        ) : null}
      </Card>

      {loading && !data ? <Spinner label="Building the performance report" /> : null}

      {data ? (
        <>
          <div className="stat-grid">
            <StatCard
              label={stockLabel}
              value={totals?.filtered ?? 0}
              hint={`${totals?.scan_days ?? 0} scan day(s)`}
              tone="blue"
            />
            <StatCard
              label="Avg D+1 return"
              value={signedPercent(d1?.avg_return_pct)}
              hint={d1?.n ? `${d1.n} stock(s) with data` : "no forward session yet"}
              tone={
                d1?.avg_return_pct === null || d1?.avg_return_pct === undefined
                  ? "gray"
                  : d1.avg_return_pct >= 0
                    ? "green"
                    : "red"
              }
            />
            <StatCard
              label="D+1 win rate"
              value={d1?.win_rate_pct === null || d1?.win_rate_pct === undefined ? "—" : `${d1.win_rate_pct}%`}
              hint={d1?.n ? `${d1.n} sampled` : "no sample"}
              tone={
                d1?.win_rate_pct === null || d1?.win_rate_pct === undefined
                  ? "gray"
                  : d1.win_rate_pct >= 50
                    ? "green"
                    : "amber"
              }
            />
            <StatCard
              label="D+3 win rate"
              value={winRateText(d3)}
              hint={d3?.n ? `${d3.n} sampled` : "no sample"}
              tone={
                d3?.win_rate_pct === null || d3?.win_rate_pct === undefined
                  ? "gray"
                  : d3.win_rate_pct >= 50
                    ? "green"
                    : "amber"
              }
            />
            <StatCard
              label="Candle cache"
              value={cache?.data_to ? formatDate(cache.data_to) : "empty"}
              hint={
                cache
                  ? `${cache.symbols} symbols · ${cache.candles} candles · fetched ${relativeTime(cache.last_fetched_at)}`
                  : ""
              }
              tone={cache?.candles ? "green" : "amber"}
            />
          </div>

          <Card title="Scan days">
            {data.days.length === 0 ? (
              <Empty message="No OI candidates were filtered in this window. Widen the dates or run an OI scan." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th className="right">Scans</th>
                      <th className="right">Filtered</th>
                      <th className="right">L / S</th>
                      {Array.from({ length: data.forward_days }).map((_unused, index) => (
                        <th key={index} className="right">
                          {offsetLabel(index)}
                          <span className="muted small"> · avg · n · win</span>
                        </th>
                      ))}
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.days.map((day) => (
                      <DayRow
                        key={day.day}
                        day={day}
                        forwardDays={data.forward_days}
                        expanded={Boolean(expanded[day.day])}
                        onToggle={() =>
                          setExpanded((current) => ({
                            ...current,
                            [day.day]: !current[day.day]
                          }))
                        }
                      />
                    ))}
                    <tr className="performance-total-row">
                      <td>
                        <strong>All days</strong>
                      </td>
                      <td className="right">—</td>
                      <td className="right">
                        <strong>{totals?.filtered ?? 0}</strong>
                      </td>
                      <td className="right">—</td>
                      {Array.from({ length: data.forward_days }).map((_unused, index) => (
                        <OffsetCell key={index} offset={totals?.offsets?.[index]} strong />
                      ))}
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
            <p className="performance-note">
              One row per stock per day; when the scanner ran several times, the latest scan
              is the entry. Each D+n cell shows the average direction-adjusted return, the
              number of stocks with a close for that session, and their win rate (share with
              a positive return).
            </p>
          </Card>
        </>
      ) : null}
    </>
  );
}

function DayRow({
  day,
  forwardDays,
  expanded,
  onToggle
}: {
  day: PerformanceDay;
  forwardDays: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr>
        <td>
          {formatDate(day.day)}
          {day.pending ? <span className="muted small"> · pending</span> : null}
        </td>
        <td className="right">{day.scans}</td>
        <td className="right">
          {day.filtered}
          {day.duplicates_collapsed > 0 ? (
            <span className="muted small"> · {day.duplicates_collapsed} dup</span>
          ) : null}
        </td>
        <td className="right">
          {day.long_count} / {day.short_count}
        </td>
        {Array.from({ length: forwardDays }).map((_unused, index) => (
          <OffsetCell key={index} offset={day.offsets[index]} />
        ))}
        <td className="right">
          <button className="btn small ghost" onClick={onToggle}>
            {expanded ? "Hide" : "Stocks"}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={forwardDays + 5} className="performance-detail">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Grade</th>
                    <th className="right">Score</th>
                    <th className="right">Scan LTP</th>
                    {Array.from({ length: forwardDays }).map((_unused, index) => (
                      <th key={index} className="right">
                        {offsetLabel(index)}
                        {day.offsets[index]?.trade_date
                          ? ` · ${formatDate(day.offsets[index].trade_date)}`
                          : ""}
                      </th>
                    ))}
                    <th className="right" title="Highest intraday high over D+1..D+4: the best exit for a long">
                      High · long
                    </th>
                    <th className="right" title="Lowest intraday low over D+1..D+4: the best exit for a short">
                      Low · short
                    </th>
                    <th title="The row's own direction at that extreme; ✓ means it was still profitable">
                      Signal fit
                    </th>
                    <th>Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {day.symbols.map((row) => (
                    <SymbolRow
                      key={row.candidate_id}
                      row={row}
                      forwardDays={forwardDays}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="performance-note">
              <strong>High · long</strong> is the highest intraday high and{" "}
              <strong>Low · short</strong> the lowest intraday low across D+1 to D+4,
              with the return each would have given. <strong>Signal fit</strong> applies
              the stock&apos;s own direction to its favourable extreme: ✓ when that best
              point still beat the scan price, ✗ when it did not.
            </p>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function SymbolRow({
  row,
  forwardDays
}: {
  row: PerformanceSymbol;
  forwardDays: number;
}) {
  return (
    <tr>
      <td>
        <strong>{row.symbol}</strong>
        <span className="muted small"> · {row.scanned_at ? formatDateTime(row.scanned_at).slice(-8) : ""}</span>
      </td>
      <td>
        <Badge tone={row.direction === "LONG" ? "green" : "red"}>{row.direction}</Badge>
      </td>
      <td>
        <Badge tone={row.grade === "A+" || row.grade === "A" ? "green" : "gray"}>
          {row.grade}
        </Badge>
      </td>
      <td className="right">{num(row.score, 1)}</td>
      <td className="right">{num(row.scan_ltp)}</td>
      {Array.from({ length: forwardDays }).map((_unused, index) => {
        const close = row.closes[index];
        const value = row.returns_pct[index];
        const high = row.highs?.[index];
        const low = row.lows?.[index];
        return (
          <td
            key={index}
            className={`right ${returnClass(value)}`}
            title={high === null || high === undefined ? undefined : `Intraday high ${num(high)} · low ${num(low)}`}
          >
            {value === null || value === undefined ? (
              "—"
            ) : (
              <>
                {signedPercent(value)}
                <div className="muted small">{close === null || close === undefined ? "no close" : num(close)}</div>
              </>
            )}
          </td>
        );
      })}
      <td className="right">
        <ExtremeCell
          extreme={row.high_low?.highest}
          returnPct={row.high_low?.best_long_return_pct}
        />
      </td>
      <td className="right">
        <ExtremeCell
          extreme={row.high_low?.lowest}
          returnPct={row.high_low?.best_short_return_pct}
        />
      </td>
      <td><SignalFit summary={row.high_low} /></td>
      <td>
        <Badge tone={coverageTone(row.coverage)}>{row.coverage}</Badge>
      </td>
    </tr>
  );
}
