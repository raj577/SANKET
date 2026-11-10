"use client";

import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Modal, Pagination, Spinner } from "@/components/ui";
import { buildQuery } from "@/lib/api";
import { formatDateTime, toneForStatus } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { AuditLog, Page } from "@/lib/types";

const PAGE_SIZE = 30;

const ACTIONS = [
  "CANDIDATE_APPROVED",
  "CANDIDATE_REJECTED",
  "SIGNAL_PUBLISHED",
  "SIGNAL_ENTRY_CHANGED",
  "SIGNAL_TARGET_CHANGED",
  "SIGNAL_STOPLOSS_CHANGED",
  "SIGNAL_CANCELLED",
  "SIGNAL_CLOSED",
  "USER_CREATED",
  "USER_UPDATED",
  "SETTINGS_UPDATED",
  "FYERS_TOKEN_UPDATED"
];

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [selected, setSelected] = useState<AuditLog | null>(null);

  const path = `/admin/audit${buildQuery({ page, page_size: PAGE_SIZE, action, entity_type: entityType })}`;
  const { data, loading, error, reload } = useApiData<Page<AuditLog>>(path);

  return (
    <>
      <Card
        title="Audit log"
        actions={<button className="btn ghost small" onClick={reload}>Refresh</button>}
      >
        <div className="filters" style={{ marginBottom: 14 }}>
          <Field label="Action">
            <select value={action} onChange={(event) => { setAction(event.target.value); setPage(1); }}>
              <option value="">All actions</option>
              {ACTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </Field>
          <Field label="Entity type">
            <input value={entityType} onChange={(event) => { setEntityType(event.target.value); setPage(1); }} placeholder="published_signal" />
          </Field>
        </div>

        <ErrorText error={error} />

        {loading && !data ? (
          <Spinner label="Loading audit log" />
        ) : data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time (IST)</th>
                    <th>Admin</th>
                    <th>Action</th>
                    <th>Entity</th>
                    <th>Entity ID</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.id}>
                      <td className="nowrap small">{formatDateTime(item.created_at)}</td>
                      <td className="small">{item.user_email || "system"}</td>
                      <td><Badge tone={toneForStatus(item.action.includes("REJECT") || item.action.includes("CANCEL") ? "REJECTED" : item.action.includes("PUBLISH") ? "PUBLISHED" : "COMPLETED")}>{item.action}</Badge></td>
                      <td className="small">{item.entity_type}</td>
                      <td className="mono small">{item.entity_id ? `${item.entity_id.slice(0, 8)}…` : "—"}</td>
                      <td>
                        <button className="btn ghost small" onClick={() => setSelected(item)}>Details</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <Empty message="No audit entries match these filters." />
        )}
      </Card>

      <Modal open={Boolean(selected)} title="Audit entry" onClose={() => setSelected(null)} wide>
        {selected ? (
          <div style={{ display: "grid", gap: 14 }}>
            <dl className="kv">
              <dt>Time</dt>
              <dd>{formatDateTime(selected.created_at)}</dd>
              <dt>Admin</dt>
              <dd>{selected.user_email || "system"}</dd>
              <dt>Action</dt>
              <dd>{selected.action}</dd>
              <dt>Entity</dt>
              <dd>{selected.entity_type} · {selected.entity_id || "—"}</dd>
            </dl>
            <div>
              <div className="section-title">Details</div>
              <pre className="code-block">{JSON.stringify(selected.details, null, 2)}</pre>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
