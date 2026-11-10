export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric"
  }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function num(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

export function signedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function toneForStatus(status: string): "green" | "red" | "amber" | "blue" | "gray" {
  switch (status) {
    case "COMPLETED":
    case "APPROVED":
    case "ACTIVE":
    case "TARGET_HIT":
      return "green";
    case "FAILED":
    case "REJECTED":
    case "STOPLOSS_HIT":
    case "CANCELLED":
      return "red";
    case "PARTIAL":
    case "PENDING":
      return "amber";
    case "RUNNING":
    case "PUBLISHED":
      return "blue";
    default:
      return "gray";
  }
}

export function toneForFreshness(freshness: string): "green" | "red" | "amber" | "gray" {
  switch (freshness) {
    case "LIVE":
      return "green";
    case "DELAYED":
      return "amber";
    case "STALE":
      return "red";
    default:
      return "gray";
  }
}

export function istDateString(daysAgo = 0): string {
  const now = new Date();
  const shifted = new Date(now.getTime() - daysAgo * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(shifted);
}