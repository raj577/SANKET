"use client";

import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Pagination, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { bytes, formatDateTime, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Archive, Page } from "@/lib/types";

const PAGE_SIZE = 25;

export default function ArchivesPage() {
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const { data, loading, error: loadError, reload } = useApiData<Page<Archive>>(
    `/admin/archives?page=${page}&page_size=${PAGE_SIZE}`
  );

  async function download(item: Archive) {
    setError(null);
    try {
      await api.download(
        `/admin/archives/${item.scan_id}/download`,
        item.csv_filename || `scan-${item.scan_id}.csv`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  return (
    <Card
      title="CSV archives"
      actions={
        <button className="btn ghost small" onClick={reload}>
          Refresh
        </button>
      }
    >
      <div className="muted small" style={{ marginBottom: 12 }}>
        Complete originals are stored on disk/S3 with a SHA-256 checksum. PostgreSQL only stores scan metadata and filtered candidates.
      </div>
      <ErrorText error={loadError || error} />
      {loading && !data ? (
        <Spinner label="Loading archives" />
      ) : data && data.items.length > 0 ? (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Scan</th>
                  <th>Started (IST)</th>
                  <th>Status</th>
                  <th>File</th>
                  <th className="right">Size</th>
                  <th>Saved</th>
                  <th>SHA-256</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.scan_id}>
                    <td className="mono small">{item.scan_id.slice(0, 8)}</td>
                    <td className="nowrap">{formatDateTime(item.started_at)}</td>
                    <td><Badge tone={toneForStatus(item.status)}>{item.status}</Badge></td>
                    <td className="mono small">{item.csv_filename || "—"}</td>
                    <td className="right">{bytes(item.csv_size_bytes)}</td>
                    <td className="nowrap small">{formatDateTime(item.csv_saved_at)}</td>
                    <td className="mono small" style={{ maxWidth: 200, wordBreak: "break-all" }}>
                      {item.csv_checksum_sha256 || "—"}
                    </td>
                    <td>
                      <button className="btn ghost small" onClick={() => download(item)}>
                        Download
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      ) : (
        <Empty message="No archived CSV files yet." />
      )}
    </Card>
  );
}
