"use client";

import { Empty } from "./ui";
import { formatDateTime, num } from "@/lib/format";
import type { PricePoint } from "@/lib/types";

export function PriceChart({
  points,
  entry,
  target,
  stopLoss,
  direction
}: {
  points: PricePoint[];
  entry: string;
  target: string;
  stopLoss: string | null;
  direction: string;
}) {
  const data = points
    .map((point) => ({ time: new Date(point.captured_at).getTime(), value: Number(point.ltp) }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));

  if (data.length < 2) {
    return <Empty message="At least two observed prices are needed for a chart." />;
  }

  const entryValue = Number(entry);
  const targetValue = Number(target);
  const stopValue = stopLoss === null ? null : Number(stopLoss);
  const candidates = [entryValue, targetValue, ...(stopValue === null ? [] : [stopValue]), ...data.map((point) => point.value)]
    .filter((value) => Number.isFinite(value));
  const rawMin = Math.min(...candidates);
  const rawMax = Math.max(...candidates);
  const padding = (rawMax - rawMin || 1) * 0.08;
  const min = rawMin - padding;
  const max = rawMax + padding;

  const width = 680;
  const height = 210;
  const padX = 52;
  const padY = 18;
  const x = (index: number) => padX + (index / (data.length - 1)) * (width - padX * 2);
  const y = (value: number) => height - padY - ((value - min) / (max - min)) * (height - padY * 2);
  const line = data.map((point, index) => `${x(index).toFixed(2)},${y(point.value).toFixed(2)}`).join(" ");
  const color = direction === "LONG" ? "#3ddc97" : "#ff6b6b";

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="price-chart" role="img" aria-label="Observed price history">
        <text x={padX} y={padY} className="chart-label">{num(rawMax)}</text>
        <text x={padX} y={height - 4} className="chart-label">{num(rawMin)}</text>
        <line x1={padX} y1={y(targetValue)} x2={width - padX} y2={y(targetValue)} className="chart-target" />
        <text x={width - padX} y={y(targetValue) - 5} textAnchor="end" className="chart-target-label">Target {num(targetValue)}</text>
        {stopValue !== null ? (
          <>
            <line x1={padX} y1={y(stopValue)} x2={width - padX} y2={y(stopValue)} className="chart-stop" />
            <text x={width - padX} y={y(stopValue) - 5} textAnchor="end" className="chart-stop-label">SL {num(stopValue)}</text>
          </>
        ) : null}
        <line x1={padX} y1={y(entryValue)} x2={width - padX} y2={y(entryValue)} className="chart-entry" />
        <polyline points={line} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
        {data.map((point, index) => (
          <circle key={`${point.time}-${index}`} cx={x(index)} cy={y(point.value)} r={2.5} fill={color} />
        ))}
      </svg>
      <div className="flex" style={{ justifyContent: "space-between", marginTop: 4 }}>
        <span className="muted small">{formatDateTime(new Date(data[0].time).toISOString())}</span>
        <span className="muted small">{formatDateTime(new Date(data[data.length - 1].time).toISOString())}</span>
      </div>
    </div>
  );
}
